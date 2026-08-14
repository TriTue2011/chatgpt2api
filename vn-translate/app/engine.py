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


#: EnViT5 học trên văn bản đã tách từ kiểu Moses nên nhả ra dạng rời: "I ca n't
#: take", "the school 's gate". Dán lại các đuôi rút gọn tiếng Anh.
_DINH_LAI = re.compile(r"\s+(n't|'s|'re|'ve|'ll|'d|'m)\b")

#: Dòng chỉ gồm 2+ từ TOÀN CHỮ CÁI, không dấu câu, không chữ số.
_DANG_TEN = re.compile(r"^[^\W\d_]+(?: [^\W\d_]+)+$")
#: Tên người dài nhất còn nhận (họ + đệm + tên, kể cả tên bốn năm chữ). Đếm TỪ
#: chứ không đếm ký tự: một câu viết hoa từng chữ vẫn có thể ngắn.
_TEN_NHIEU_TU_NHAT = 5


def la_ten_rieng(s: str) -> bool:
    """Dòng này là TÊN RIÊNG đứng một mình (tên người trong ảnh chụp chat…).

    NLLB không có ngữ cảnh để dịch một cái tên trần nên nó BỊA ra cả câu — đo
    thật 13/08 trên ảnh chụp Zalo: "Vu Minh Tuan" → "You know what?",
    "Nguyễn Huy Văn" → "What is it?". Model 1.3B còn tệ hơn: "I'm going to kill
    you." Đây không phải dịch dở mà là CHẾ NỘI DUNG, nên chặn ở đây.

    Nhận diện hẹp, cố ý bỏ sót hơn là bắt nhầm: từ nào cũng viết hoa, chỉ chữ
    cái và dấu cách, ít nhất hai từ, không quá dài. Câu chat thường có ít nhất
    một từ viết thường nên không dính; nhắn một từ ("Được") cũng không dính.

    ĐÁNH ĐỔI đã cân nhắc: tiêu đề tiếng Anh kiểu Title Case không dấu câu
    ("Time Awareness") sẽ giữ nguyên thay vì được dịch. Người đọc vẫn thấy bản
    gốc — nhẹ hơn nhiều so với việc bịa một câu chưa ai từng viết.
    """
    s = s.strip()
    if not _DANG_TEN.match(s):
        return False
    tu = s.split()
    return len(tu) <= _TEN_NHIEU_TU_NHAT and all(t[:1].isupper() for t in tu)


def _cat_manh(text: str) -> list[str]:
    """Một dòng → TỪNG CÂU riêng; câu đơn quá dài cắt thêm ở dấu phẩy.

    Vì sao từng câu chứ không gom tới ~400 ký tự như bản đầu: EnViT5/NLLB học
    trên CẶP CÂU — đưa nhiều câu trong một lượt là mời model NUỐT câu. Đo thật
    13/08: chuỗi 3 câu ("Now, I'm going to grab my knife. My knife, which I
    damaged… cut a bone. I know it sounds stupid.") dịch ra đúng 2 câu, câu
    cuối biến mất không dấu vết. Dịch từng câu thì không có gì để nuốt.
    """
    ra: list[str] = []
    for cau in _CAT_CAU.split(text):
        cau = cau.strip()
        while len(cau) > _TRAN_MANH:
            cat = cau.rfind(",", _TRAN_MANH // 2, _TRAN_MANH)
            if cat < 0:
                cat = cau.rfind(" ", _TRAN_MANH // 2, _TRAN_MANH)
            if cat < 0:
                cat = _TRAN_MANH
            ra.append(cau[:cat + 1].strip())
            cau = cau[cat + 1:].strip()
        if cau:
            ra.append(cau)
    return ra or ([text] if text else [])


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
            if not co_chu(dong) or la_ten_rieng(dong):
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
    """Bọc CTranslate2 + tokenizer, kèm thang model tự chuyển khi lỗi.

    HAI máy dịch, chọn theo CẶP ngôn ngữ:

    - ``en↔vi`` → **EnViT5** (VietAI, 275M, nhúng sẵn trong image). Model
      chuyên đúng một cặp nên thắng đậm model đa ngữ: trên bộ test PhoMT,
      EnViT5 hơn M2M100 — cùng họ kiến trúc với NLLB và to gấp 4,4 lần —
      khoảng 9,5 BLEU cả hai chiều, và vượt cả Google Translate.
    - cặp còn lại (ja/ko/zh…) → **NLLB-200**, vì EnViT5 chỉ biết en và vi.

    EnViT5 hỏng thì lượt đó rơi xuống NLLB chứ không báo lỗi cho người dùng.

    Vì sao không bỏ hẳn NLLB: đo thật 13/08 trên chính câu chủ máy gửi, NLLB
    dịch việt→anh nuốt cả vế sau và có câu ngược hẳn nghĩa ("Anh cho em xin
    lại số tài khoản" → "I'll give you the account number"). Nhưng nó là thứ
    duy nhất phủ được nhật/hàn/trung nên vẫn giữ cho các cặp đó.
    """

    def __init__(self) -> None:
        self.models = [m.strip() for m in
                       os.getenv("TT_MODELS", _MODELS_MAC_DINH).split(",") if m.strip()]
        self.model_dir = os.getenv("TT_MODEL_DIR", "/data/models")
        self.threads = int(os.getenv("TT_THREADS", "4"))
        # TT_THIET_BI=cuda cho bản GPU (RTX 2060S trên máy NVR, khảo sát
        # 14/08: dịch lô nhanh ~10×). Trên cuda dùng int8_float16 — card
        # CC ≥ 7.0 chạy lớp int8 bằng tensor core, lớp còn lại fp16;
        # trên cpu giữ "default" (model đã là int8 sẵn).
        self.thiet_bi = os.getenv("TT_THIET_BI", "cpu").strip() or "cpu"
        self.kieu_tinh = os.getenv("TT_KIEU_TINH", "").strip() or (
            "int8_float16" if self.thiet_bi == "cuda" else "default")
        # Lô đưa vào model MỖI LƯỢT decode. CPU giữ 16 (to hơn không nhanh
        # thêm, chỉ tốn RAM); GPU mặc định 64 — card ăn lô to mới bõ chuyến
        # (đo 14/08: lô 16 GPU chỉ nhanh 1,66× CPU).
        mac_dinh_lo = "64" if self.thiet_bi == "cuda" else "16"
        self.lo_model = max(1, int(os.getenv("TT_LO_MODEL", mac_dinh_lo)))
        self.chi_so = 0            # model đang dùng trong self.models
        self.loi_lien_tiep = 0
        self._tr = None            # ctranslate2.Translator
        self._tok = None           # transformers tokenizer
        self._lock = threading.Lock()
        self.model_dang_dung = ""
        # EnViT5 — đường chính cho en↔vi. Đặt TT_ENVIT5_DIR="" để tắt hẳn,
        # mọi cặp quay về NLLB như bản cũ.
        self.envit5_dir = os.getenv("TT_ENVIT5_DIR", "/opt/envit5").strip()
        self._e_tr = None
        self._e_tok = None
        self._e_hong = False       # đã thử nạp và hỏng → thôi thử lại

    # ── EnViT5 (en↔vi) ──────────────────────────────────────────────────────
    def _co_envit5(self) -> bool:
        """Nạp EnViT5 nếu chưa nạp. Thiếu/hỏng thì trả False, KHÔNG raise —
        gọi xong lượt dịch vẫn phải chạy được bằng NLLB."""
        if self._e_tr is not None:
            return True
        if self._e_hong or not self.envit5_dir or not os.path.isdir(self.envit5_dir):
            return False
        try:
            import ctranslate2
            import transformers
            self._e_tr = ctranslate2.Translator(
                self.envit5_dir, device=self.thiet_bi,
                compute_type=self.kieu_tinh, inter_threads=1,
                intra_threads=self.threads)
            self._e_tok = transformers.AutoTokenizer.from_pretrained(self.envit5_dir)
            logger.info("đã nạp EnViT5 cho en↔vi: %s", self.envit5_dir)
            return True
        except Exception as exc:
            self._e_hong = True
            self._e_tr = self._e_tok = None
            logger.warning("nạp EnViT5 lỗi, en↔vi quay về NLLB: %s", str(exc)[:200])
            return False

    def _dich_envit5(self, manh: list[str], nguon: str, dich: str) -> list[str]:
        """EnViT5 nhận tiền tố ngôn ngữ NGUỒN trong chính văn bản ("vi: …") và
        trả về kèm tiền tố đích ("en: …") — khác hẳn NLLB (token FLORES)."""
        vao = [self._e_tok.convert_ids_to_tokens(self._e_tok.encode(f"{nguon}: {m}"))
               for m in manh]
        kq = self._e_tr.translate_batch(vao, beam_size=4,
                                        max_batch_size=self.lo_model,
                                        batch_type="examples")
        ra: list[str] = []
        for r in kq:
            s = self._e_tok.decode(
                self._e_tok.convert_tokens_to_ids(r.hypotheses[0]),
                skip_special_tokens=True).strip()
            for tien_to in (f"{dich}: ", "en: ", "vi: "):
                if s.startswith(tien_to):
                    s = s[len(tien_to):]
                    break
            # Model hay bọc cả câu trong ngoặc kép dù bản gốc không có.
            if len(s) > 1 and s[0] == '"' == s[-1] and '"' not in s[1:-1]:
                s = s[1:-1]
            ra.append(_DINH_LAI.sub(r"\1", s).strip())
        return ra

    # ── nạp / chuyển model ──────────────────────────────────────────────────
    def _nap_mot(self, repo: str) -> None:
        import ctranslate2
        import transformers
        from huggingface_hub import snapshot_download

        duong = snapshot_download(repo, cache_dir=self.model_dir)
        self._tr = ctranslate2.Translator(duong, device=self.thiet_bi,
                                          compute_type=self.kieu_tinh,
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
        return self._tr is not None or self._e_tr is not None

    def khoi_dong(self) -> None:
        """Nạp sẵn EnViT5 (cặp dùng nhiều nhất, nằm sẵn trong image nên nhanh).

        NLLB nạp LƯỜI — chỉ khi có người dịch nhật/hàn/trung, vì nó phải tải
        600 MB từ mạng. Trước đây nạp sẵn NLLB là bắt mọi lần khởi động chờ
        tải, kể cả khi cả ngày chỉ dịch anh↔việt.
        """
        with self._lock:
            if not self._co_envit5() and self._tr is None:
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

        # Mổ dòng MỘT LẦN, dùng chung cho cả hai máy dịch: dòng trống và tên
        # riêng không được lọt vào model nào cả.
        khung, can = _khung(texts)
        if not can:
            return list(texts)

        if {nguon, dich} == {"en", "vi"}:
            with self._lock:
                if self._co_envit5():
                    try:
                        return _ghep(khung, self._dich_envit5(can, nguon, dich))
                    except Exception as exc:
                        # Rơi xuống NLLB ngay trong lượt này: người dùng thà
                        # nhận bản dịch kém hơn còn hơn nhận thông báo lỗi.
                        logger.warning("EnViT5 lỗi, lượt này dùng NLLB: %s",
                                       str(exc)[:200])
        with self._lock:
            if self._tr is None:
                self._nap()
            try:
                ra = _ghep(khung, self._dich_nllb(can, nguon, dich))
                self.loi_lien_tiep = 0
                return ra
            except Exception as exc:
                self.loi_lien_tiep += 1
                logger.warning("dịch lỗi (%d/%d) trên %s: %s", self.loi_lien_tiep,
                               NGUONG_LOI, self.model_dang_dung, str(exc)[:200])
                if self.loi_lien_tiep < NGUONG_LOI:
                    raise
                self._chuyen_model()
                ra = _ghep(khung, self._dich_nllb(can, nguon, dich))
                self.loi_lien_tiep = 0
                return ra

    def _dich_nllb(self, manh: list[str], nguon: str, dich: str) -> list[str]:
        """Thân dịch NLLB — gọi khi ĐÃ giữ _lock và model đã nạp."""
        fl_nguon, fl_dich = ISO2FLORES[nguon], ISO2FLORES[dich]
        self._tok.src_lang = fl_nguon
        vao = [self._tok.convert_ids_to_tokens(self._tok.encode(m)) for m in manh]
        kq = self._tr.translate_batch(
            vao, target_prefix=[[fl_dich]] * len(vao),
            beam_size=4, max_batch_size=self.lo_model, batch_type="examples",
        )
        ra: list[str] = []
        for r in kq:
            tokens = r.hypotheses[0][1:]  # bỏ token ngôn ngữ đích ở đầu
            ra.append(self._tok.decode(
                self._tok.convert_tokens_to_ids(tokens), skip_special_tokens=True))
        return ra


engine = Engine()
