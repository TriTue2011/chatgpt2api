"""Danh mục 19 giọng tiếng Việt NghiTTS — VITS 22,05 kHz chạy qua sherpa-onnx.

Cùng nguyên tắc Piper/Kokoro/VieNeu: DANH MỤC nằm trong image (file này, chỉ vài
KB chữ), MODEL nằm ngoài trên volume ``data/nghitts/<mã giọng>/`` — tải bằng
``scripts/download_nghitts_voices.py``. Chọn giọng bằng id ``nghi:<mã giọng>``.

**Vì sao ghim SHA-256 từng file.** Nguồn tải là API công khai
``https://nghitts.app/api/model/<Tên>.onnx`` — không có phiên bản, chủ trang thay
file dưới cùng một tên lúc nào cũng được. Ghim băm khiến bản thay đổi bị TỪ CHỐI
ngay lúc tải thay vì lặng lẽ đổi chất giọng, hoặc tệ hơn là nạp một đồ hình ONNX
chưa ai xem qua. Băm lấy từ luuquangvu/wyoming-vietnamese và đã đối chiếu lại
với API thật ngày 2026-08-11.

Hai nhóm giọng khác nhau đúng một chỗ trong file cấu hình: ``espeak.voice`` là
``vi`` (Bắc/chuẩn) hay ``vi-vn-x-south`` (Nam bộ) — trùng đúng hai nhãn ngôn ngữ
mà danh mục Piper đang dùng.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://nghitts.app/api/model"
DEFAULT_ID = "ngoc-huyen-moi"

# Tên file trên đĩa — đặt cố định để engine không phải biết tên hiển thị.
MODEL_FILE = "model.onnx"
CONFIG_FILE = "model.onnx.json"
TOKENS_FILE = "tokens.txt"
# Dấu ghi nhận model đã được vá metadata (xem sherpa_metadata bên dưới).
PREPARED_FILE = ".model.onnx.prepared.json"

SAMPLE_RATE = 22050

# File cấu hình dùng chung cho cả nhóm, nên chỉ có đúng hai giá trị băm.
_CONFIG_SHA256_NORTH = "971f57f8d504223fee5b40d664f503cf769baf7db21f7d2ae0554a75d07de2f8"
_CONFIG_SHA256_SOUTH = "77c49591a8786c1842e06c328360cb5ccd6aa8b57322b2373e19c69f81452a0a"

LANG_NORTH = "vi"
LANG_SOUTH = "vi-vn-x-south"


@dataclass(frozen=True)
class NghiVoice:
    """Một giọng: mã, tên hiển thị (cũng là tên file trên API), và băm model."""

    id: str
    name: str
    model_sha256: str
    south: bool = False

    @property
    def language(self) -> str:
        return LANG_SOUTH if self.south else LANG_NORTH

    @property
    def model_remote(self) -> str:
        return f"{self.name}.onnx"

    @property
    def config_remote(self) -> str:
        return f"{self.name}.onnx.json"

    @property
    def config_sha256(self) -> str:
        return _CONFIG_SHA256_SOUTH if self.south else _CONFIG_SHA256_NORTH

    @property
    def artifacts(self) -> tuple[tuple[str, str, str], ...]:
        """((tên trên API, tên trên đĩa, băm), ...) — model trước, cấu hình sau."""
        return (
            (self.model_remote, MODEL_FILE, self.model_sha256),
            (self.config_remote, CONFIG_FILE, self.config_sha256),
        )


VOICES: tuple[NghiVoice, ...] = (
    NghiVoice("ban-mai", "Ban Mai",
              "9f599998f244511edd3df757febc0653ee94bfdbe673740f25c98c9b9b374984"),
    NghiVoice("chieu-thanh", "Chiếu Thành",
              "5b3059395e1d2f3d7499deaf3463615b5281c607465ea274d82ce84d93d61ac3", True),
    NghiVoice("duy-onyx-moi", "Duy Onyx (mới)",
              "b4ebfc949c3330cf3d44520133cb1ba3460bb4218ff5286e28ba10fcfa898ac8"),
    NghiVoice("duy-oryx", "Duy Oryx",
              "0d6f6b95eee7256f18115c09ad1cbdb69acddf87761549ec1a7decd19a4eba5c"),
    NghiVoice("lac-phi", "Lạc Phi",
              "c6e496c69c05f6043efd9967f0fb98d34b7cf94b0e698de43169253d34b318b2"),
    NghiVoice("mai-phuong", "Mai Phương",
              "3d8384d05a0569be1a0a4da12d7582e7d0500b1f55139584e70f310dac92b01b"),
    NghiVoice("minh-khang", "Minh Khang",
              "3c95962901b3c3dd03d6de636625f6f3608877d69d7fb5cb20f9c26b202f3453"),
    NghiVoice("minh-quang", "Minh Quang",
              "0a559df4c4eaab442e0d2007f32888f87567900dfe1a4e9f1632f64070090e17"),
    NghiVoice("manh-dung", "Mạnh Dũng",
              "b5e4d3b55e02847082a07ddca34bccaca201bc83a4441b974accac699645bfe0"),
    NghiVoice("my-tam", "Mỹ Tâm",
              "9a0c576d3366aa336ab56d782e2a0db174a26f6a1629cf418d2cf059d45ff6c1"),
    NghiVoice("my-tam-real", "Mỹ Tâm Real",
              "140f4b6f3c487338613f7c1b2842950110178404f7e9b5abed7640acd8956267", True),
    NghiVoice("ngoc-huyen-moi", "Ngọc Huyền (mới)",
              "88bc21477831dd99759cff164f0ab270e258faf435d01741f0211ff8620255e2"),
    NghiVoice("ngoc-ngan", "Ngọc Ngạn",
              "c03a71201f51336fe937f12e54781520cb3bf629fa6adb3943314e29a58a9133"),
    NghiVoice("phuong-trang", "Phương Trang",
              "78e7f514503652a666e3e4b4d0d8fdc42f03d81a775a521b3119d1d7e6fc303f"),
    NghiVoice("thanh-phuong-viettel", "Thanh Phương Viettel",
              "f7d806e82e785729caf950893c2caa19a94ca79acfa1cd0deb2fc654cd61df68"),
    NghiVoice("thien-tam", "Thiện Tâm",
              "2ac4616193b00c68d10997670ad617c6a3798a05262638b4811b2448e77c85dc", True),
    NghiVoice("tran-thanh", "Trấn Thành",
              "c3235ad51d99f5ce7d147ceb28db2ad2fe3500131d8ec77e804e6451ec293759"),
    NghiVoice("tai-an", "Tài An",
              "74e911f0c6d32e3e14811271f5da896befadbdea418272b72c7ad228c6322498"),
    NghiVoice("viet-thao", "Việt Thảo",
              "f8cad266cfed6018390752326373379411b85efcfca21441e41e31a5aa4a6daf"),
)

BY_ID: dict[str, NghiVoice] = {v.id: v for v in VOICES}


def get(voice_id: str) -> NghiVoice | None:
    """Giọng theo mã, None nếu mã lạ. Caller quyết định báo lỗi hay rơi mặc định."""
    return BY_ID.get((voice_id or "").strip())


def sherpa_metadata(config: dict) -> tuple[tuple[str, str], ...]:
    """Bảy trường metadata mà sherpa-onnx đòi nhưng bản xuất NghiTTS không có.

    Model NghiTTS là VITS kiểu Piper nhưng xuất ra với `metadata_props` RỖNG
    (đã đo: 0 key). Nạp thẳng thì sherpa-onnx dừng ngay ở
    `offline-tts-vits-model.cc` với "'sample_rate' does not exist in the
    metadata". Mọi thứ sherpa cần đều nằm sẵn trong model.onnx.json, chỉ là
    nằm sai chỗ — hàm này rút ra để ghi vào đúng chỗ.

    Kiểm luôn ba điều kiện của cấu hình: đúng tần số lấy mẫu, đúng một giọng,
    và phiên âm bằng espeak. Sai một trong ba thì dừng, vì lúc đó metadata ta
    ghi vào sẽ mô tả sai model và tiếng đọc ra sẽ méo chứ không lỗi rõ ràng.

    Cách làm học từ luuquangvu/wyoming-vietnamese (`download.py`).
    """
    audio = config.get("audio")
    if not isinstance(audio, dict) or audio.get("sample_rate") != SAMPLE_RATE:
        raise ValueError(f"Cấu hình NghiTTS phải là audio {SAMPLE_RATE} Hz.")
    if config.get("num_speakers") != 1:
        raise ValueError("Cấu hình NghiTTS phải có đúng một giọng.")
    if config.get("phoneme_type") != "espeak":
        raise ValueError("Cấu hình NghiTTS phải dùng âm vị espeak.")
    espeak = config.get("espeak")
    voice = espeak.get("voice") if isinstance(espeak, dict) else None
    if not isinstance(voice, str) or not voice:
        raise ValueError("Cấu hình NghiTTS không có espeak.voice.")
    return (
        ("sample_rate", str(SAMPLE_RATE)),
        ("n_speakers", "1"),
        ("model_type", "vits"),
        ("comment", "piper"),
        ("language", "Vietnamese"),
        ("voice", voice),
        ("has_espeak", "1"),
    )


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint không nhận số âm.")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _text_field(field_number: int, value: str) -> bytes:
    raw = value.encode("utf-8")
    return _varint((field_number << 3) | 2) + _varint(len(raw)) + raw


def encode_onnx_metadata(entries: tuple[tuple[str, str], ...]) -> bytes:
    """Mã hoá `metadata_props` của ONNX ModelProto — không cần gói `onnx`.

    Ghi được bằng cách NỐI THÊM vào cuối file .onnx là nhờ tính chất của
    protobuf: nối hai bản mã hoá của cùng một message tương đương việc gộp
    trường, và `metadata_props` (trường 14) là trường lặp nên các mục thêm vào
    cuối được gộp vào danh sách sẵn có. Nhờ vậy không phải giải mã rồi mã hoá
    lại cả đồ hình 60 MB, cũng không phải kéo thêm phụ thuộc `onnx` vào image.
    """
    out = bytearray()
    tag = _varint((14 << 3) | 2)
    for key, value in entries:
        entry = _text_field(1, key) + _text_field(2, value)
        out.extend(tag)
        out.extend(_varint(len(entry)))
        out.extend(entry)
    return bytes(out)


def tokens_from_config(config: dict) -> list[str]:
    """Bảng token cho sherpa-onnx, dựng từ ``phoneme_id_map`` của file cấu hình.

    NghiTTS không phát hành tokens.txt; nó nằm sẵn trong model.onnx.json dưới
    dạng ánh xạ âm vị → id. Trả về danh sách token xếp theo id, dòng thứ i ứng
    với id i. Ném ValueError nếu ánh xạ khuyết hoặc trùng id — thà dừng còn hơn
    sinh bảng lệch làm giọng đọc ra tiếng vô nghĩa.
    """
    raw = config.get("phoneme_id_map")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Cấu hình NghiTTS không có phoneme_id_map.")
    by_id: dict[int, str] = {}
    for token, ids in raw.items():
        if not isinstance(token, str) or "\n" in token or "\r" in token:
            raise ValueError("Âm vị NghiTTS phải là chuỗi một dòng.")
        if not isinstance(ids, list) or not ids:
            raise ValueError(f"Âm vị {token!r} không có id nào.")
        for tid in ids:
            if isinstance(tid, bool) or not isinstance(tid, int) or tid < 0:
                raise ValueError(f"Âm vị {token!r} có id không hợp lệ.")
            if tid in by_id:
                raise ValueError(f"Id token {tid} bị trùng.")
            by_id[tid] = token
    if sorted(by_id) != list(range(len(by_id))):
        raise ValueError("Id token NghiTTS phải liên tục và bắt đầu từ 0.")
    return [by_id[i] for i in range(len(by_id))]
