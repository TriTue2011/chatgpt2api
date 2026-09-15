"""Kokoro tiếng Việt + phiên âm vig2p — 14 giọng, 24 kHz, chạy ONNX trên CPU.

Nguồn: `contextboxai/Kokoro-Vietnamese` (Apache-2.0), fine-tune Kokoro-82M cho
tiếng Việt, huấn luyện cùng bộ phiên âm `vig2p` (sea-g2p + "Vocab Adapter" đổi
ký hiệu sang bảng từ vựng cố định của Kokoro, mỗi thanh một ký hiệu riêng).

Vì sao thêm họ giọng này — đo 15/09/2026 trên máy chủ, vòng đọc → STT nghe lại,
18 câu thường (không tính dãy «ma má mà mả mã mạ»):

    họ giọng              sai thanh     ghi chú
    giọng người (FLEURS)  0,14 %        mốc của chính giám khảo
    Kokoro-Vietnamese     0,04 %        1/2464 âm tiết, 14 giọng
    VieNeu                0,65 %
    Piper                 0,73 %        ngang đọc trầm → nghe ra huyền
    NghiTTS               0,80 %        («nay→này», «chị→chỉ»)

Phiên âm espeak `vi` của Piper/NghiTTS KHÔNG làm rơi thanh (đo trên 7.500 âm tiết
FLEURS, lỗi toàn ở từ ngoại) — lỗi nằm trong trọng số model, nên gắn vig2p vào
giọng cũ không chữa được; phải dùng model huấn luyện cùng nó.

File này KHÔNG import gì trong gói ở đầu file: `scripts/download_kokoro_vi.py`
nạp thẳng nó để chạy trên máy trắng (cùng nếp `nghitts_voices.py`).
"""
from __future__ import annotations

import io
import pickle
import re
import zipfile
from dataclasses import dataclass

REPO = "contextboxai/Kokoro-Vietnamese"
MODEL_FILE = "kokoro_vi.onnx"
CONFIG_FILE = "config.json"
VOICE_DIR = "voices"            # voices/<mã>.npy — đổi từ .pt lúc tải
SAMPLE_RATE = 24000
DEFAULT_ID = "hung_thinh"


@dataclass(frozen=True)
class KokoroViVoice:
    id: str
    name: str

    @property
    def hf_file(self) -> str:
        return f"voicepacks/{self.id}.pt"

    @property
    def npy_file(self) -> str:
        return f"{VOICE_DIR}/{self.id}.npy"


#: Theo voices.json của repo model (không ghi giới tính: repo không khai).
VOICES: tuple[KokoroViVoice, ...] = (
    KokoroViVoice("hung_thinh", "Hưng Thịnh"),
    KokoroViVoice("diem_trinh", "Diễm Trinh"),
    KokoroViVoice("mai_linh", "Mai Linh"),
    KokoroViVoice("mai_loan", "Mai Loan"),
    KokoroViVoice("manh_dung", "Mạnh Dũng"),
    KokoroViVoice("my_yen", "Mỹ Yến"),
    KokoroViVoice("ngoc_huyen", "Ngọc Huyền"),
    KokoroViVoice("phat_tai", "Phát Tài"),
    KokoroViVoice("thanh_dat", "Thành Đạt"),
    KokoroViVoice("thuc_trinh", "Thục Trinh"),
    KokoroViVoice("tuan_ngoc", "Tuấn Ngọc"),
    KokoroViVoice("storyvert", "Storyvert"),
    KokoroViVoice("duc_an", "Đức An"),
    KokoroViVoice("duc_duy", "Đức Duy"),
)


def get(voice_id: str) -> KokoroViVoice | None:
    return next((v for v in VOICES if v.id == voice_id), None)


# ── Phiên âm ────────────────────────────────────────────────────────────────

_CUM = re.compile(r"([^\w\s']+)", re.UNICODE)


def phien_am(text: str, pipeline=None) -> str:
    """Chữ Việt → chuỗi âm vị theo bảng ký hiệu Kokoro-Vietnamese.

    Khác `vig2p.phonemize_text` ở MỘT chỗ: đưa cả mệnh đề vào sea-g2p thay vì
    từng từ rời. sea-g2p chọn đọc tiếng Việt hay tiếng Anh DỰA VÀO NGỮ CẢNH, nên
    tách từ ra là mất ngữ cảnh — đo 15/09/2026: «bay» đứng một mình ra `beɪ`,
    «máy bay» ra `baj`; mọi giọng đọc «nhưng may không» thành «nhưng mê không».
    Trên văn bản FLEURS, âm tiết dạng tiếng Việt bị đọc kiểu Anh giảm 13 → 2
    (hai cái còn lại là từ ngoại). Phần đổi ký hiệu (`fix_phonemes`) vẫn áp cho
    TỪNG từ vì nó cần chữ gốc (th/tr/s/gi) — đúng cách vig2p làm lúc huấn luyện.

    CHUẨN HOÁ cả câu TRƯỚC khi tách mệnh đề: «8h30», «1.250.000», «28°C» nở ra
    thành nhiều từ và chứa dấu chấm/phẩy, tách trước thì số từ lệch và cả vig2p
    gốc lẫn bản này đều phiên hỏng («8h30» → `8hˈaː↗t↗0`, đo 15/09/2026).

    Mệnh đề nào sea-g2p vẫn trả số từ khác chữ đã chuẩn hoá thì lùi về đúng
    đường của vig2p, không đoán cách ghép.
    """
    from vig2p import phonemize_text
    from vig2p.core import fix_phonemes

    if pipeline is None:
        pipeline = _pipeline()
    ra: list[str] = []
    for doan in _CUM.split(pipeline.normalizer.normalize(text or "")):
        if not doan:
            continue
        if _CUM.fullmatch(doan):
            ra.append(fix_phonemes(doan))
            continue
        tu = doan.split()
        if not tu:
            ra.append(" ")
            continue
        am = str(pipeline.g2p.convert(doan)).split()
        if len(am) == len(tu):
            ra.append(" " + " ".join(fix_phonemes(a, source_text=w) for w, a in zip(tu, am)) + " ")
        else:
            ra.append(" " + phonemize_text(doan) + " ")
    return re.sub(r"\s+([^\w\s])", r"\1", " ".join("".join(ra).split())).strip()


_PIPE = None


def _pipeline():
    global _PIPE
    if _PIPE is None:
        from sea_g2p import SEAPipeline
        _PIPE = SEAPipeline("vi")
    return _PIPE


def input_ids(phonemes: str, vocab: dict[str, int], context_length: int):
    """Âm vị → mảng id (1, n) có token 0 ở hai đầu, như lúc huấn luyện."""
    import numpy as np

    ids = [vocab[p] for p in phonemes if p in vocab]
    if len(ids) + 2 > context_length:
        raise ValueError(f"câu quá dài cho Kokoro: {len(ids) + 2} > {context_length}")
    return np.asarray([[0, *ids, 0]], dtype=np.int64)


def chon_style(voicepack, so_am_vi: int):
    """Voicepack (N, 1, 256): Kokoro lấy vector theo ĐỘ DÀI chuỗi âm vị."""
    i = min(max(so_am_vi, 1), voicepack.shape[0]) - 1
    return voicepack[i].astype("float32")


# ── Đọc voicepack .pt không cần torch ───────────────────────────────────────

class _Luu:
    """Đánh dấu một storage trong pickle của torch (chỉ cần khoá và kiểu)."""

    def __init__(self, khoa: str, kieu: str) -> None:
        self.khoa, self.kieu = khoa, kieu


def doc_voicepack_pt(du_lieu: bytes):
    """Đọc voicepack `.pt` (torch.save của MỘT tensor float32) thành numpy.

    Image không có torch (hơn 700 MB chỉ để đọc 14 file 500 KB), nên tự đọc
    định dạng zip của torch: `data.pkl` mô tả tensor, `data/<khoá>` là byte
    thô. Unpickler chỉ nhận đúng ba tên cần thiết — file từ mạng không được
    phép gọi hàm tuỳ ý qua pickle.
    """
    import numpy as np

    z = zipfile.ZipFile(io.BytesIO(du_lieu))
    ten_pkl = next(n for n in z.namelist() if n.endswith("data.pkl"))
    goc = ten_pkl[: -len("data.pkl")]

    def _dung(storage, offset, size, stride, *_):
        if storage.kieu != "FloatStorage":
            raise ValueError(f"voicepack không phải float32: {storage.kieu}")
        tho = np.frombuffer(z.read(f"{goc}data/{storage.khoa}"), dtype="<f4")
        n = int(np.prod(size))
        return tho[offset:offset + n].reshape(size).copy()

    class _Unpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if (module, name) == ("torch._utils", "_rebuild_tensor_v2"):
                return _dung
            if module == "torch" and name == "FloatStorage":
                return "FloatStorage"
            if (module, name) == ("collections", "OrderedDict"):
                import collections
                return collections.OrderedDict
            raise pickle.UnpicklingError(f"không cho phép {module}.{name}")

        def persistent_load(self, pid):
            if not (isinstance(pid, tuple) and pid and pid[0] == "storage"):
                raise pickle.UnpicklingError(f"persistent id lạ: {pid!r}")
            return _Luu(str(pid[2]), str(pid[1]))

    kq = _Unpickler(io.BytesIO(z.read(ten_pkl))).load()
    if not hasattr(kq, "shape") or kq.ndim != 3 or kq.shape[1:] != (1, 256):
        raise ValueError(f"voicepack sai hình dạng: {getattr(kq, 'shape', None)}")
    return kq
