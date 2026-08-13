"""Engine dịch NLLB-200 chạy CPU qua CTranslate2 — không LLM, không bên thứ ba.

Vì sao NLLB-200 thay cho Argos: một model duy nhất phủ 200 ngôn ngữ (Argos phải
tải 8 gói cho 5 thứ tiếng, và cặp vi↔ja phải bắc cầu hai lần qua tiếng Anh —
NLLB dịch THẲNG vi→ja trong một lượt). Bản distilled-600M int8 chạy tốt trên
CPU. Giấy phép CC-BY-NC-4.0 (dùng cá nhân/nội bộ ổn, KHÔNG bán dịch vụ dịch).

TỰ CHUYỂN MODEL KHI LỖI (yêu cầu chủ máy): ``TT_MODELS`` là danh sách xếp hạng,
phân cách bằng dấu phẩy. Model đang dùng mà tải hỏng, hoặc dịch lỗi
``NGUONG_LOI`` lần LIÊN TIẾP, thì bị nhả ra và engine nhảy sang model kế —
người dùng thấy bản dịch chậm hơn một nhịp thay vì thấy lỗi. Hết vòng thì quay
lại model đầu (có thể chỉ nghẽn mạng lúc tải).

Tải model: ``huggingface_hub.snapshot_download`` về volume ``TT_MODEL_DIR``
(mặc định /data/models) — lần đầu ~600 MB, các lần sau đọc từ đĩa, không mạng.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

#: ISO 639-1 (mã LibreTranslate dùng) → mã FLORES-200 của NLLB. Chỉ liệt kê
#: ngôn ngữ đã kiểm; thêm dần khi cần — NLLB có đủ 200.
ISO2FLORES: dict[str, str] = {
    "en": "eng_Latn", "vi": "vie_Latn", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "zh-Hans": "zho_Hans", "zh-Hant": "zho_Hant",
    "fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn", "ru": "rus_Cyrl",
    "th": "tha_Thai", "id": "ind_Latn", "km": "khm_Khmr", "lo": "lao_Laoo",
    "pt": "por_Latn", "it": "ita_Latn", "nl": "nld_Latn", "ar": "arb_Arab",
    "hi": "hin_Deva", "tr": "tur_Latn", "pl": "pol_Latn", "uk": "ukr_Cyrl",
}
TEN_NGON_NGU: dict[str, str] = {
    "en": "English", "vi": "Vietnamese", "ja": "Japanese", "ko": "Korean",
    "zh-Hans": "Chinese", "zh-Hant": "Chinese (Traditional)", "fr": "French",
    "de": "German", "es": "Spanish", "ru": "Russian", "th": "Thai",
    "id": "Indonesian", "km": "Khmer", "lo": "Lao", "pt": "Portuguese",
    "it": "Italian", "nl": "Dutch", "ar": "Arabic", "hi": "Hindi",
    "tr": "Turkish", "pl": "Polish", "uk": "Ukrainian",
}

#: Dịch lỗi ngần này lần LIÊN TIẾP thì bỏ model hiện tại, chuyển model kế.
NGUONG_LOI = 2

_MODELS_MAC_DINH = (
    "JustFrederik/nllb-200-distilled-600M-ct2-int8,"
    "JustFrederik/nllb-200-distilled-1.3B-ct2-int8"
)

# Câu dài phải cắt: NLLB suy giảm mạnh khi vượt cỡ huấn luyện (~512 token).
# Cắt theo câu, gom lại ~400 ký tự một mảnh.
_CAT_CAU = re.compile(r"(?<=[.!?。！？])\s+")
_TRAN_MANH = 400


def co_chu(s: str) -> bool:
    """Chuỗi này có chữ để mà dịch không.

    NLLB nhận đầu vào KHÔNG có chữ thì không im lặng — nó BỊA ra một câu. Đo
    thật 13/08: khối YAML nhiều dòng trống dịch xong mọc đầy dòng "Tương tự:",
    mỗi dòng trống một câu rác. Nên mảnh không có chữ phải đi vòng qua model.
    """
    return any(c.isalpha() for c in s)


def _cat_manh(text: str) -> list[str]:
    """Một dòng dài → các mảnh ~_TRAN_MANH ký tự, cắt ở ranh giới câu."""
    if len(text) <= _TRAN_MANH:
        return [text]
    ra: list[str] = []
    dem = ""
    for cau in _CAT_CAU.split(text):
        if dem and len(dem) + len(cau) + 1 > _TRAN_MANH:
            ra.append(dem)
            dem = cau
        else:
            dem = f"{dem} {cau}".strip() if dem else cau
    if dem:
        ra.append(dem)
    return ra or [text]


#: Một dòng sau khi mổ: (thụt lề trái, các mảnh cần dịch, đuôi phải). Dòng
#: không có chữ thì mảnh rỗng và cả dòng nằm nguyên trong phần "trái".
Dong = tuple[str, list[str], str]


def _khung(texts: list[str]) -> tuple[list[list[Dong]], list[str]]:
    """Mổ lô văn bản thành khung dòng + danh sách mảnh CẦN dịch.

    Tách riêng khỏi ``Engine._dich_khoa`` để kiểm được mà không cần model: hai
    thứ dễ hỏng ở đây (dòng trống lọt vào model, thụt lề bị nuốt) đều là chuyện
    ghép chữ thuần tuý.

    Thụt lề giữ bằng cách CẮT RA rồi đắp lại: tokenizer NLLB bỏ khoảng trắng
    biên khi decode, mà mất thụt lề là hỏng luôn YAML/mã người ta nhờ dịch.
    """
    khung: list[list[Dong]] = []
    can: list[str] = []
    for t in texts:
        cac_dong: list[Dong] = []
        for dong in (t or "").split("\n"):
            if not co_chu(dong):
                cac_dong.append((dong, [], ""))
                continue
            trai = dong[:len(dong) - len(dong.lstrip())]
            phai = dong[len(dong.rstrip()):]
            manh = _cat_manh(dong.strip())
            can.extend(manh)
            cac_dong.append((trai, manh, phai))
        khung.append(cac_dong)
    return khung, can


def _ghep(khung: list[list[Dong]], ra_manh: list[str]) -> list[str]:
    """Khung + bản dịch từng mảnh → lô văn bản, đúng số dòng như bản gốc."""
    ra: list[str] = []
    vt = 0
    for cac_dong in khung:
        chu: list[str] = []
        for trai, manh, phai in cac_dong:
            if not manh:
                chu.append(trai)
                continue
            phan = [x.strip() for x in ra_manh[vt:vt + len(manh)]]
            vt += len(manh)
            chu.append(f"{trai}{' '.join(phan)}{phai}")
        ra.append("\n".join(chu))
    return ra


class KhongCoNgonNgu(ValueError):
    """Mã ngôn ngữ ngoài ISO2FLORES."""


class Engine:
    """Bọc CTranslate2 + tokenizer, kèm thang model tự chuyển khi lỗi."""

    def __init__(self) -> None:
        self.models = [m.strip() for m in
                       os.getenv("TT_MODELS", _MODELS_MAC_DINH).split(",") if m.strip()]
        self.model_dir = os.getenv("TT_MODEL_DIR", "/data/models")
        self.threads = int(os.getenv("TT_THREADS", "4"))
        self.chi_so = 0            # model đang dùng trong self.models
        self.loi_lien_tiep = 0
        self._tr = None            # ctranslate2.Translator
        self._tok = None           # transformers tokenizer
        self._lock = threading.Lock()
        self.model_dang_dung = ""

    # ── nạp / chuyển model ──────────────────────────────────────────────────
    def _nap_mot(self, repo: str) -> None:
        import ctranslate2
        import transformers
        from huggingface_hub import snapshot_download

        duong = snapshot_download(repo, cache_dir=self.model_dir)
        self._tr = ctranslate2.Translator(duong, device="cpu",
                                          inter_threads=1, intra_threads=self.threads)
        # Bản CT2 cộng đồng giữ nguyên tokenizer HF trong cùng repo.
        self._tok = transformers.AutoTokenizer.from_pretrained(duong)
        self.model_dang_dung = repo
        self.loi_lien_tiep = 0
        logger.info("đã nạp model %s", repo)

    def _nap(self) -> None:
        """Nạp model đầu tiên còn sống trong thang. Hết vòng thì raise."""
        loi_cuoi: Exception | None = None
        for buoc in range(len(self.models)):
            i = (self.chi_so + buoc) % len(self.models)
            try:
                self._nap_mot(self.models[i])
                self.chi_so = i
                return
            except Exception as exc:  # tải hỏng / thiếu file / OOM
                loi_cuoi = exc
                logger.warning("nạp model %s lỗi: %s", self.models[i], str(exc)[:200])
        raise RuntimeError(f"không nạp được model nào trong thang: {loi_cuoi}")

    def _chuyen_model(self) -> None:
        """Nhả model hiện tại, nhảy sang model kế trong thang."""
        hong = self.model_dang_dung
        self._tr = None
        self._tok = None
        self.model_dang_dung = ""
        self.chi_so = (self.chi_so + 1) % len(self.models)
        logger.warning("model %s lỗi %d lần liên tiếp → chuyển sang %s",
                       hong, NGUONG_LOI, self.models[self.chi_so])
        self._nap()

    def san_sang(self) -> bool:
        return self._tr is not None

    def khoi_dong(self) -> None:
        with self._lock:
            if self._tr is None:
                self._nap()

    # ── dịch ────────────────────────────────────────────────────────────────
    def dich(self, texts: list[str], nguon: str, dich: str) -> list[str]:
        """Dịch lô. Mỗi phần tử giữ nguyên vị trí; rỗng đi thẳng qua.

        Model dịch lỗi ``NGUONG_LOI`` lần liên tiếp → tự chuyển model kế rồi
        thử lại lô này MỘT lần nữa (yêu cầu chủ máy: tự động chuyển model).
        """
        if nguon not in ISO2FLORES:
            raise KhongCoNgonNgu(f"{nguon} is not supported")
        if dich not in ISO2FLORES:
            raise KhongCoNgonNgu(f"{dich} is not supported")
        with self._lock:
            if self._tr is None:
                self._nap()
            try:
                ra = self._dich_khoa(texts, nguon, dich)
                self.loi_lien_tiep = 0
                return ra
            except Exception as exc:
                self.loi_lien_tiep += 1
                logger.warning("dịch lỗi (%d/%d) trên %s: %s", self.loi_lien_tiep,
                               NGUONG_LOI, self.model_dang_dung, str(exc)[:200])
                if self.loi_lien_tiep < NGUONG_LOI:
                    raise
                self._chuyen_model()
                ra = self._dich_khoa(texts, nguon, dich)
                self.loi_lien_tiep = 0
                return ra

    def _dich_khoa(self, texts: list[str], nguon: str, dich: str) -> list[str]:
        """Thân dịch thật — gọi khi ĐÃ giữ _lock và model đã nạp."""
        fl_nguon, fl_dich = ISO2FLORES[nguon], ISO2FLORES[dich]
        self._tok.src_lang = fl_nguon

        khung, can = _khung(texts)
        if not can:
            return list(texts)

        vao = [self._tok.convert_ids_to_tokens(self._tok.encode(m)) for m in can]
        kq = self._tr.translate_batch(
            vao, target_prefix=[[fl_dich]] * len(vao),
            beam_size=4, max_batch_size=16, batch_type="examples",
        )
        ra_manh: list[str] = []
        for r in kq:
            tokens = r.hypotheses[0][1:]  # bỏ token ngôn ngữ đích ở đầu
            ra_manh.append(self._tok.decode(
                self._tok.convert_tokens_to_ids(tokens), skip_special_tokens=True))
        return _ghep(khung, ra_manh)


engine = Engine()
