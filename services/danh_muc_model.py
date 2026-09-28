"""Danh mục MỌI model c2a cần tải — một chỗ duy nhất cho thẻ web «Model cần tải» và README.

Chủ máy 28/09/2026: "Phần tải model nên có thêm hướng dẫn ngay trong c2a, cái nào cần tải thì
hướng dẫn hết". Ảnh Docker chỉ mang chương trình chạy model (piper, sherpa-onnx, onnxruntime);
mọi model nằm ở volume dữ liệu và tải bằng ``scripts/download_*.py`` — trước đây lệnh tải chỉ lộ
ra trong câu báo lỗi lúc đã dùng tới, hoặc rải rác trong HUONG_DAN.md.

Mỗi mục kiểm "đã tải" bằng ĐÚNG hàm mà c2a dùng lúc chạy (``vcfg.stt_model_dir``,
``nhin_nha.co_yolo``…) — không chạy script ``--check`` (13 tiến trình mỗi lần mở trang).

Mức độ tính THEO CẤU HÌNH đang chạy:
* ``can``  — tính năng đang bật / giọng đang gán mà thiếu model này thì lỗi.
* ``nen``  — nên có (tăng chất lượng, có đường lùi).
* ``tuy_chon`` — chỉ cần khi dùng tính năng đó.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

LENH = "docker exec c2a /app/.venv/bin/python scripts/"


@dataclass
class Muc:
    ma: str
    nhom: str
    ten: str
    dung_cho: str
    dung_luong: str
    script: str
    kiem: Callable[[], bool]
    ho: tuple[str, ...] = ()          # họ giọng (``engines._ho_engine``) mà mục này phục vụ
    ghi_chu: str = ""
    them: list[tuple[str, str]] = field(default_factory=list)   # (lệnh tải thêm, mô tả)


def _co(p) -> bool:
    try:
        return bool(p) and p.is_dir() and any(p.iterdir())
    except OSError:
        return False


def _muc() -> list[Muc]:
    from services import nhin_nha, yolo_nha
    from services.voice import config as v

    m, b = nhin_nha.model_yolo(), nhin_nha.bo_mat()
    return [
        Muc("stt_vi", "Giọng nói — nghe", "Nghe tiếng Việt (Zipformer)",
            "Nhận giọng nói tiếng Việt: Home Assistant Assist, tin thoại Zalo/Telegram, mic camera",
            "~100 MB", "download_stt_model.py", lambda: v.stt_model_dir() is not None),
        Muc("vad", "Giọng nói — nghe", "Cắt đoạn lời nói (Silero VAD)",
            "Tách chỗ có tiếng nói chính xác hơn; không có thì tự cắt theo độ lớn tiếng",
            "0,6 MB", "download_silero_vad.py", lambda: v.vad_model_path() is not None),
        Muc("stt_en", "Giọng nói — nghe", "Nghe tiếng Anh (Parakeet-TDT)",
            "Nhận giọng nói tiếng Anh (cổng Wyoming 10701, dạy học tiếng Anh)",
            "~600 MB", "download_stt_en_model.py", lambda: v.stt_en_model_dir() is not None),
        Muc("stt_sense", "Giọng nói — nghe", "Nghe Trung / Nhật / Hàn (SenseVoice)",
            "Tab Dịch, đàm thoại, cổng Wyoming 10702–10704",
            "~230 MB", "download_stt_da_ngu.py --sense", lambda: v.stt_sense_model_dir() is not None),
        Muc("piper", "Giọng nói — đọc", "Giọng Piper (nhẹ nhất)",
            "Giọng đọc mặc định «ngochuyennew» — nhanh, chạy máy yếu",
            "~64 MB", "download_piper_voices.py --pack minimal",
            lambda: _co(v.PIPER_DIR), ho=("piper",),
            them=[("download_piper_voices.py --pack full", "cả 19 giọng (manhdung, banmai…), ~1,2 GB")]),
        Muc("nghi", "Giọng nói — đọc", "NghiTTS (19 giọng Việt)",
            "Giọng «nghi:…» — tự nhiên, nhanh (dùng cho camera, trợ lý)",
            "~64 MB", "download_nghitts_voices.py", v.nghi_ready, ho=("nghi",),
            them=[("download_nghitts_voices.py --all", "cả 19 giọng, ~1,2 GB")]),
        Muc("zerotts", "Giọng nói — đọc", "ZeroTTS (8 giọng giữ thanh điệu)",
            "Giọng «zerotts:…» — hay nhất, cần CPU khá", "~900 MB", "download_zerotts.py",
            lambda: v.zerotts_model_dir() is not None, ho=("zerotts",),
            them=[("download_zerotts.py --int8", "thêm bản int8 cho máy yếu")]),
        Muc("kokorovi", "Giọng nói — đọc", "Kokoro Việt (14 giọng)",
            "Giọng «kokorovi:…»", "~330 MB", "download_kokoro_vi.py --all",
            lambda: v.kokoro_vi_dir() is not None, ho=("kokorovi",)),
        Muc("vieneunano", "Giọng nói — đọc", "VieNeu Nano", "Giọng «vieneunano:…» — nhẹ, nhanh",
            "~400 MB", "download_vieneu_nano.py", lambda: v.vieneu_nano_dir() is not None,
            ho=("vieneunano",)),
        Muc("vieneu", "Giọng nói — đọc", "VieNeu Turbo", "Giọng «vieneu:…» — nặng, cần CPU mạnh",
            "~1,2 GB RAM khi chạy", "download_vieneu_model.py", v.vieneu_model_ready, ho=("vieneu",)),
        Muc("kokoro", "Giọng nói — đọc", "Kokoro tiếng Anh", "Giọng «kokoro:…» — đọc tiếng Anh",
            "~305 MB", "download_kokoro_model.py", lambda: v.kokoro_model_dir() is not None,
            ho=("kokoro",)),
        Muc("tts_da_ngu", "Giọng nói — đọc", "Đọc Trung / Nhật / Hàn",
            "Tab Dịch đọc kết quả tiếng Trung (Kokoro đa ngữ) và Nhật/Hàn (Supertonic)",
            "~260 MB", "download_tts_da_ngu.py", lambda: _co(v.KOKORO_ZH_DIR) and _co(v.SUPERTONIC_DIR)),
        Muc("yolo", "Nhìn nhà (camera)", f"Nhận vật thể YOLO26 ({m.ma})",
            "Canh camera, tìm người, trông xe — thấy người/xe/vật",
            f"~{m.mb:g} MB".replace(".", ","), f"download_nhin_nha.py --yolo {m.ma}", nhin_nha.co_yolo),
        Muc("khuon_mat", "Nhìn nhà (camera)", f"Nhận khuôn mặt InsightFace ({b.ma})",
            "Nhận người nhà, hỏi tên người lạ, trông xe biết người nhà lấy xe",
            f"~{b.zip_mb:g} MB tải (giữ 2 tệp)".replace(".", ","), f"download_nhin_nha.py --mat {b.ma}",
            nhin_nha.co_mat,
            ghi_chu="Chỉ dùng phi thương mại (giấy phép InsightFace)."),
        Muc("dang_nguoi", "Nhìn nhà (camera)", "Nhận dáng người YOLO26-pose",
            "Báo ngã — thấy người chuyển sang nằm (17 điểm khớp)", "~12 MB",
            "download_nhin_nha.py --dang",
            lambda: (nhin_nha.THU_MUC / yolo_nha.MODEL_DANG.tep).is_file()),
        Muc("tu_dien", "Dịch", "Từ điển Anh/Trung/Nhật/Hàn → Việt",
            "Tra nghĩa từng từ trong tab Dịch (không tốn lượt AI)", "~44 MB", "tai_tu_dien.py",
            lambda: _co(Path(v.DATA_DIR) / "tudien")),
    ]


def _ho_dang_dung() -> set[str]:
    """Họ giọng đang gán (mặc định + từng loa) và họ Home Assistant Assist đã gọi — thiếu là câm."""
    try:
        from services.voice import engines
        return {engines._ho_engine(g) for g in engines._giong_dang_gan() if g} | set(engines._GIU_ASSIST)
    except Exception:  # noqa: BLE001 — không đọc được sổ loa thì không suy "cần"
        return set()


def _muc_do(m: Muc, ho: set[str]) -> str:
    from services import canh_camera_nha
    from services.voice import config as v

    if m.ma == "stt_vi":
        return "can" if v.is_stt_enabled() else "nen"
    if m.ma == "stt_en":
        return "can" if (v._sub("stt") or {}).get("en_enabled") else "tuy_chon"
    if m.ma == "vad":
        return "nen" if v.is_stt_enabled() else "tuy_chon"
    if m.ma == "dang_nguoi":
        from services import bao_nga
        return "can" if bao_nga.cai_dat()["bat"] else "tuy_chon"
    if m.ma in ("yolo", "khuon_mat"):
        try:
            return "can" if canh_camera_nha.cfg().get("bat") else "tuy_chon"
        except Exception:  # noqa: BLE001
            return "tuy_chon"
    if m.ho and set(m.ho) & ho:
        return "can"
    return "tuy_chon"


def danh_muc() -> list[dict[str, Any]]:
    """Cho web: mỗi model một dòng — đã tải chưa, cần không, lệnh tải."""
    ho = _ho_dang_dung()
    ra = []
    for m in _muc():
        try:
            da_tai = bool(m.kiem())
        except Exception:  # noqa: BLE001 — kiểm hỏng coi như chưa có
            da_tai = False
        ra.append({"ma": m.ma, "nhom": m.nhom, "ten": m.ten, "dung_cho": m.dung_cho,
                   "dung_luong": m.dung_luong, "muc_do": _muc_do(m, ho), "da_tai": da_tai,
                   "lenh": LENH + m.script,
                   "them": [{"lenh": LENH + l, "mo_ta": t} for l, t in m.them],
                   "ghi_chu": m.ghi_chu})
    return ra
