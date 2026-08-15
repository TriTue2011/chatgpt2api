#!/usr/bin/env python3
"""Kiểm phát âm giọng đọc bằng vòng khép kín: TTS đọc ra → STT của chính máy
nghe lại → so với chữ gốc.

**Vì sao vòng khép kín, không chỉ đo phổ tần.** Cách đo hiển nhiên hơn là lấy
năng lượng dải cao ở 70 ms đầu mỗi từ (vùng phụ âm đầu). Đo thật thì nó chỉ phân
biệt được âm xát mạnh — x, s — còn h/ph/kh/th thấp ở MỌI giọng, kể cả giọng
người nghe thấy rõ ràng, nên không kết luận được giọng nào rụng âm. Cho chính
máy nghe lại thì mỗi câu ra một phán quyết đúng/sai đếm được, và dùng lại y
nguyên cho cả năm tiếng mà không phải thiết kế lại thước đo cho từng hệ âm vị.

Hai phép đo bù nhau nên bảng tiếng Việt in cả hai. Vòng TTS→STT bắt được âm BỊ
THAY hoặc BỊ MẤT; âm còn mà ĐỌC QUÁ NHẸ thì máy vẫn nghe ra trong khi tai người
đã thấy lệch — cột "âm xát" đo đúng chỗ đó.

**Cách đọc kết quả.** Câu mà MỌI giọng đều sai là hạn chế của STT (hoặc do chính
tả đầu ra khác đầu vào, hay gặp ở tiếng Nhật vì chữ Hán), KHÔNG phải lỗi giọng —
bảng tách riêng nhóm đó ra. Chỉ những câu mà giọng khác đọc đúng mới tính là
giọng này rụng âm.

**Cột "đúng" bão hoà, cột "lượt hụt" thì không.** Cột đúng/N lấy đa số các lần
đọc lại, nên đọc lại càng nhiều lần thì các giọng càng dồn về cùng một điểm: âm
hụt hai lần trên năm vẫn tính là đạt. Xếp hạng bằng riêng cột đó là xếp hạng
nhiễu — đo tiếng Nhật 14/08/2026 ra bốn giọng cùng 12/13 trong khi số lượt hụt
là 2/55 với 10/55, chênh nhau năm lần. Có ``--lap > 1`` thì bảng in thêm cột
**lượt hụt** đếm thẳng từng lượt nghe, và hai giọng cùng điểm thì giọng hụt ít
lần hơn đứng trên.

Chạy trong container, vì model nằm trên volume::

    docker exec c2a /app/.venv/bin/python /app/scripts/kiem_phat_am.py vi
    docker exec c2a /app/.venv/bin/python /app/scripts/kiem_phat_am.py ja --buoc 4,16
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.voice import config as vcfg  # noqa: E402
from services.voice import engines as eng  # noqa: E402

# (câu đọc, các âm phải nghe lại được, nhãn phụ âm đang thử)
#
# Tiếng Việt viết âm cần kiểm dưới dạng "x-" (âm ĐẦU) hay "-ng" (âm CUỐI) chứ
# không phải cả âm tiết. Lý do đo thật: STT hay nghe lệch thanh điệu hoặc nguyên
# âm ("kem" → "Kèm", "quýt" → "quyết") — so cả âm tiết thì những lệch đó bị tính
# thành rụng phụ âm, trong khi phụ âm vẫn nguyên. So theo âm đầu/âm cuối thì
# phép đo trả lời đúng một câu hỏi: phụ âm còn hay mất.
BO_TEST: dict[str, tuple[tuple[str, tuple[str, ...], str], ...]] = {
    # Đủ phụ âm đầu tiếng Việt, rồi ba câu cuối cho phụ âm cuối.
    "vi": (
        ("xin chào các bạn", ("x-", "ch-"), "x · ch"),
        ("số sáu và số bảy", ("s-", "b-"), "s · b"),
        ("phở bò rất ngon", ("ph-", "r-"), "ph · r"),
        ("khó khăn lắm", ("kh-",), "kh"),
        ("mùa thu về rồi", ("th-", "v-"), "th · v"),
        ("trời mưa to quá", ("tr-", "m-"), "tr · m"),
        ("nhà em ở gần đây", ("nh-", "g-"), "nh · g"),
        ("ngày mai nghỉ học", ("ng-", "ngh-"), "ng · ngh"),
        ("giá vàng hôm nay", ("gi-",), "gi"),
        ("hoa hồng màu đỏ", ("h-",), "h"),
        ("đi làm về muộn", ("đ-", "l-"), "đ · l"),
        ("bàn ghế bằng gỗ", ("gh-",), "gh"),
        ("quả quýt rất ngọt", ("qu-",), "qu"),
        ("con cá vàng nhỏ", ("c-",), "c"),
        ("tôi tên là nam", ("t-", "n-"), "t · n"),
        ("kem không đường", ("k-",), "k"),
        ("da tay hơi khô", ("d-",), "d"),
        ("học sinh lớp một", ("-c", "-nh", "-p"), "cuối: c · nh · p"),
        ("hát vang bài ca", ("-t", "-ng"), "cuối: t · ng"),
        ("cách làm bánh mì", ("-ch", "-nh"), "cuối: ch · nh"),
    ),
    "en": (
        ("she sells sea shells", ("she", "sells", "shells"), "sh · s"),
        ("i think about this thing", ("think", "this", "thing"), "th · ng"),
        ("very fine white wine", ("very", "fine", "white"), "v · f · w"),
        ("cheese and jam", ("cheese", "jam"), "ch · j"),
        ("please measure it again", ("measure", "again"), "zh"),
        ("the red lorry is yellow", ("red", "lorry", "yellow"), "r · l · y"),
        ("a big black dog", ("big", "black", "dog"), "b · k · d · g"),
        ("happy people clapping", ("happy", "people"), "h · p"),
        ("the zoo has zebras and foxes", ("zoo", "zebras", "foxes"), "z · ks"),
        # Không dùng từ chỉ số ("nine", "one"): STT viết lại thành chữ số 9, 1.
        ("my mother is not near", ("mother", "not", "near"), "n · m"),
    ),
    "zh": (
        ("八百八十八块钱", ("八", "百"), "b"),
        ("苹果很甜很好", ("苹", "果"), "p · g"),
        ("妈妈买了马", ("妈", "买"), "m"),
        ("飞机场很大", ("飞", "机"), "f · j"),
        ("大家好吗", ("大", "家"), "d"),
        ("天天听音乐", ("天", "听"), "t"),
        ("你好朋友", ("你", "好"), "n · h"),
        ("老师来了", ("老", "师"), "l · sh"),
        ("请求你帮忙", ("请", "求"), "q"),
        ("学习中文很难", ("学", "习"), "x"),
        ("我知道这个", ("知", "道"), "zh"),
        ("吃饭的时间", ("吃", "饭"), "ch"),
        ("认真工作", ("认", "真"), "r"),
        ("再见朋友", ("再", "见"), "z"),
        ("从来没有过", ("从", "来"), "c"),
        ("四十三个人", ("四", "十", "三"), "s"),
    ),
    # Viết bằng chữ Hán như văn bản thật, nhưng chấp nhận CẢ cách viết kana
    # ("今日|きょう" = nghe ra chữ nào cũng tính đạt).
    #
    # Vì sao phải có phần sau dấu |: bộ nghe tiếng Nhật viết ra kana ở nhiều
    # chỗ mà câu gốc viết chữ Hán (今日 → きょう, 時間 → じかん, 写真 →
    # しゃしん). Đó là ĐỌC ĐÚNG mà GHI khác chữ, không phải rụng âm. Đo ngày
    # 14/08/2026 khi chưa có chỗ này: ba câu bị loại khỏi bảng vì "mọi giọng
    # đều sai", 10 giọng còn lại dồn vào 8–12/13 và thứ hạng ĐẢO giữa hai lần
    # chạy — tức bảng không tách nổi giọng nào với giọng nào, mà nhìn vẫn như
    # một bảng xếp hạng thật.
    "ja": (
        ("今日はいい天気ですね", ("今日|きょう", "天気|てんき"), "k · t"),
        ("私は日本語を勉強します", ("日本語|にほんご", "勉強|べんきょう"), "n · b"),
        ("時間がありません", ("時間|じかん",), "j"),
        ("写真を撮ってください", ("写真|しゃしん",), "sh"),
        ("電話番号を教えて", ("電話|でんわ", "番号|ばんごう"), "d · b"),
        ("駅はどこですか", ("駅|えき",), "e"),
        ("音楽を聞きます", ("音楽|おんがく",), "ng"),
        ("三つの質問", ("質問|しつもん",), "sh · ts"),
        ("会社に行きます", ("会社|かいしゃ",), "k · sh"),
        ("よろしくお願いします", ("願い|ねがい",), "y · n"),
    ),
    "ko": (
        ("안녕하세요 반갑습니다", ("안녕", "반갑"), "ㅇ · ㅂ"),
        ("감사합니다 정말로", ("감사", "정말"), "ㄱ · ㅈ"),
        ("오늘 날씨가 좋아요", ("오늘", "날씨"), "ㄴ · ㅆ"),
        ("한국어를 공부해요", ("한국", "공부"), "ㅎ · ㄱ"),
        ("전화번호가 뭐예요", ("전화", "번호"), "ㅈ · ㅂ"),
        ("커피 한 잔 주세요", ("커피", "주세요"), "ㅋ · ㅍ"),
        ("빨리 가야 해요", ("빨리",), "ㅃ"),
        ("사진을 찍었어요", ("사진",), "ㅅ · ㅉ"),
        ("택시를 타고 왔어요", ("택시",), "ㅌ"),
        ("맛있는 음식이에요", ("음식",), "ㅁ · ㅅ"),
    ),
}

_A_DONG = ("zh", "ja", "ko")   # không tách chữ bằng dấu cách

# Dấu THANH tiếng Việt (huyền sắc ngã hỏi nặng) — bỏ khi so, vì đang đo phụ âm.
# Không bỏ dấu CHỮ (â ă ê ô ơ ư): đó là chữ khác, không phải thanh điệu.
_DAU_THANH = frozenset(("\u0300", "\u0301", "\u0303", "\u0309", "\u0323"))   # huyền sắc ngã hỏi nặng

# Âm đầu và âm cuối tiếng Việt, xếp dài trước để khớp dài nhất (ngh trước ng).
_AM_DAU = ("ngh", "ng", "nh", "ch", "tr", "th", "ph", "kh", "gh", "gi", "qu",
           "b", "c", "d", "đ", "g", "h", "k", "l", "m", "n", "p", "r", "s",
           "t", "v", "x")
_AM_CUOI = ("ng", "nh", "ch", "c", "m", "n", "p", "t")

# Những CHỮ khác nhau nhưng cùng một ÂM, nên máy nghe không tách được và bảng
# không được tính là rụng. Giọng đang đo phiên âm bằng espeak `vi` (Bắc bộ):
# d, gi, r đều đọc /z/; s và x đều /s/; ch và tr đều /tɕ/. Máy nghe "da" ra
# "ra" thì âm /z/ vẫn còn — chỉ là chữ khác. Ở âm cuối thì -t/-c và -n/-ng lẫn
# nhau theo phương ngữ, nên chỉ đòi CÒN âm cuối, không đòi đúng chữ; mất hẳn
# ("hát" → "hà") vẫn bị bắt.
_CUNG_AM_DAU = {"d": "z", "gi": "z", "r": "z",
                "s": "s", "x": "s",
                "ch": "tɕ", "tr": "tɕ"}
_CUNG_AM_CUOI = {"t": "t/c", "c": "t/c", "n": "n/ng", "ng": "n/ng"}


def _chuan(s: str) -> str:
    """Bỏ dấu câu, hạ chữ thường, gộp dấu cách — giữ nguyên dấu tiếng Việt."""
    s = unicodedata.normalize("NFC", (s or "").lower())
    s = "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)
    return " ".join(s.split())


def _bo_thanh(s: str) -> str:
    ra = unicodedata.normalize("NFD", s)
    return unicodedata.normalize(
        "NFC", "".join(c for c in ra if c not in _DAU_THANH))


def _am_dau(tu: str) -> str:
    for am in _AM_DAU:
        if tu.startswith(am):
            return am
    return ""


def _am_cuoi(tu: str) -> str:
    for am in _AM_CUOI:
        if tu.endswith(am):
            return am
    return ""


def _nghe_thay(dich: str, ra: str, lang: str) -> bool:
    """Âm `dich` có nghe lại được trong `ra` không.

    "x-" = âm đầu, "-ng" = âm cuối, còn lại = cả từ. Tiếng Việt so sau khi bỏ
    dấu thanh, và âm đầu phải khớp TRỌN: "n-" không ăn khớp với "nhà".
    Dấu | ngăn các cách VIẾT cùng một âm ("今日|きょう") — nghe ra cách nào
    cũng tính đạt, vì phép đo hỏi âm còn hay mất, không hỏi chính tả.
    """
    if "|" in dich:
        return any(_nghe_thay(x, ra, lang) for x in dich.split("|") if x)
    r = _chuan(ra)
    if lang in _A_DONG:
        return _chuan(dich).replace(" ", "") in r.replace(" ", "")
    if lang == "en":
        # So theo chuỗi con, không theo từ: tiếng Anh ghép từ nên STT viết
        # "sea shells" thành "seashells" — âm /ʃ/ vẫn đọc đủ, chỉ khác cách
        # tách từ. Bắt buộc đúng ranh giới từ thì phép đo báo oan.
        return _chuan(dich) in r
    tu = [_bo_thanh(t) for t in r.split()]
    if dich.endswith("-"):
        can = _CUNG_AM_DAU.get(dich[:-1], dich[:-1])
        return any(_CUNG_AM_DAU.get(_am_dau(t), _am_dau(t)) == can
                   and _am_dau(t) for t in tu)
    if dich.startswith("-"):
        can = _CUNG_AM_CUOI.get(dich[1:], dich[1:])
        return any(_CUNG_AM_CUOI.get(_am_cuoi(t), _am_cuoi(t)) == can
                   and _am_cuoi(t) for t in tu)
    return _bo_thanh(_chuan(dich)) in tu


def _manh_am_xat(giong: str) -> float | None:
    """Sức mạnh âm xát /s/ (chữ x và s) — tỉ lệ năng lượng >4 kHz trên ≤2 kHz.

    Vì sao vẫn cần phép đo phổ tần bên cạnh vòng TTS→STT: vòng khép kín bắt được
    âm BỊ THAY hoặc BỊ MẤT, nhưng âm còn mà ĐỌC QUÁ NHẸ thì máy vẫn nghe ra
    trong khi tai người đã thấy lệch ("xin" nghe như "chin"). Đo phổ chỉ đáng
    tin với âm xát mạnh nên chỉ dùng cho x và s; lấy giá trị nhỏ hơn của hai.
    """
    import io
    import wave

    import numpy as np

    diem = []
    for chu in ("xin", "sáu"):
        w = wave.open(io.BytesIO(eng.synthesize(chu, giong)))
        rate = w.getframerate()
        song = (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                .astype(np.float32) / 32768.0)
        khung = int(0.01 * rate)
        bat = next((i * khung for i in range(len(song) // khung)
                    if np.sqrt((song[i * khung:(i + 1) * khung] ** 2).mean()) > 0.003),
                   None)
        if bat is None:
            return None
        doan = song[bat:bat + int(0.07 * rate)]
        if len(doan) < 16:
            return None
        pho = np.abs(np.fft.rfft(doan * np.hanning(len(doan))))
        tan = np.fft.rfftfreq(len(doan), 1 / rate)
        diem.append(float(pho[tan > 4000].sum())
                    / max(float(pho[tan <= 2000].sum()), 1e-9))
    return min(diem)


def _giong_can_do(lang: str) -> list[str]:
    """Giọng đã tải của tiếng đó. zh/ja/ko: một 'giọng' là một sid của model."""
    if lang in _A_DONG:
        return ["mặc định"]
    dsach = vcfg.voice_catalog()
    if lang == "en":
        chon = [v for v in dsach if str(v.get("language", "")) == "en"]
    else:
        chon = [v for v in dsach if str(v.get("language", "")).startswith("vi")]
    return [v["id"] for v in chon if v.get("downloaded")]


def _doc(cau: str, giong: str, lang: str, buoc: int) -> bytes:
    if lang == "zh":
        sid = -1 if giong == "mặc định" else int(giong)
        return eng.synthesize_da_ngu(cau, "zh", sid=sid)
    if lang in ("ja", "ko"):
        if not buoc:
            sid = -1 if giong == "mặc định" else int(giong)
            return eng.synthesize_da_ngu(cau, lang, sid=sid)
        return _doc_supertonic(cau, lang, buoc)
    return eng.synthesize(cau, giong)


def _doc_supertonic(cau: str, lang: str, buoc: int) -> bytes:
    """Gọi thẳng engine để đổi num_steps — đường sản xuất ghim cứng 4 bước."""
    import sherpa_onnx

    tts = eng._get_supertonic()
    gc = sherpa_onnx.GenerationConfig()
    gc.sid = vcfg.supertonic_sid(lang)
    gc.num_steps = buoc
    gc.speed = 1.0
    gc.extra["lang"] = lang
    audio = tts.generate(cau, gc)
    return eng._pcm_to_wav(
        eng._float_to_pcm16(audio.samples), int(audio.sample_rate), 2, 1)


def do_mot_tieng(lang: str, giong_ds: list[str], buoc: int = 0,
                 lap: int = 1) -> None:
    """Đo một tiếng. `lap` > 1 thì mỗi câu đọc nhiều lần rồi lấy đa số.

    Cần lặp vì VITS đọc NGẪU NHIÊN mỗi lần (bộ dự đoán độ dài có nhiễu): đo một
    mẫu thì một phụ âm chập chờn có thể hiện ra là đạt hay rụng tuỳ lần chạy.
    Lấy đa số thì "rụng" nghĩa là rụng phần lớn số lần, còn âm chỉ hụt một vài
    lần được xếp riêng thành "chập chờn" — với người nghe thì cũng là lỗi, nhưng
    là lỗi khác loại nên không trộn vào.
    """
    bo = BO_TEST[lang]
    tong_dich = sum(len(t[1]) for t in bo)
    print(f"\n=== tiếng {lang} · {len(giong_ds)} giọng × {len(bo)} câu "
          f"({tong_dich} âm cần nghe lại)"
          + (f" · đọc lại {lap} lần/câu" if lap > 1 else "")
          + (f" · num_steps={buoc}" if buoc else ""))
    # (giọng, câu) → âm rụng (đa số lần) và âm chập chờn (thiểu số lần)
    rung: dict[tuple[str, int], list[str]] = {}
    chap_chon: dict[tuple[str, int], list[str]] = {}
    diem: dict[str, tuple[int, int]] = {}
    # (giọng, câu) → (số LƯỢT nghe hụt, tổng số lượt nghe). Cột "đúng" lấy đa
    # số nên nó BÃO HOÀ khi đọc lại nhiều lần: âm hụt hai lần trên năm vẫn được
    # tính là đạt, và mấy giọng gần nhau dồn hết vào cùng một điểm. Đo tiếng
    # Nhật 14/08/2026 dính đúng chỗ này — 4 giọng cùng 12/13 mà số lần hụt chênh
    # nhau hơn hai lần. Đếm thẳng số lượt thì thứ hạng mới hiện ra.
    luot: dict[tuple[str, int], tuple[int, int]] = {}
    for giong in giong_ds:
        dung = 0
        for i, (cau, dich, _nhan) in enumerate(bo):
            so_sai = dict.fromkeys(dich, 0)
            mau = ""
            for _ in range(max(1, lap)):
                try:
                    ra = eng.transcribe(_doc(cau, giong, lang, buoc), lang=lang)
                except Exception as exc:
                    print(f"  {giong}: LỖI {str(exc)[:140]}")
                    for d in dich:
                        so_sai[d] += 1
                    continue
                mau = ra
                for d in dich:
                    if not _nghe_thay(d, ra, lang):
                        so_sai[d] += 1
            mat = [d for d, n in so_sai.items() if n * 2 > lap]
            hut = [d for d, n in so_sai.items() if 0 < n * 2 <= lap]
            luot[(giong, i)] = (sum(so_sai.values()), max(1, lap) * len(dich))
            dung += len(dich) - len(mat)
            if mat:
                rung[(giong, i)] = mat
            if hut:
                chap_chon[(giong, i)] = hut
            if mat or hut:
                dau = "/".join(mat) + ("~" + "/".join(hut) if hut else "")
                print(f"  {giong:26s} [{dau}] ← \"{mau[:60]}\"")
        diem[giong] = (dung, tong_dich)

    # Câu mà PHẦN LỚN giọng đều sai: hoặc STT nghe không ra, hoặc cả họ model
    # đọc kém — một nhóm giọng khác họ mới phân biệt được hai khả năng đó. Dù là
    # khả năng nào thì cũng không dùng để xếp hạng giọng trong CÙNG họ.
    nguong = max(2, int(0.7 * len(giong_ds)))
    phan_lon_sai = {
        i for i in range(len(bo))
        if sum(1 for g in giong_ds if (g, i) in rung) >= nguong
    }
    moi_giong_sai = phan_lon_sai
    xat = "  âm xát" if lang == "vi" else ""
    cot_luot = f"{'lượt hụt':>12s}" if lap > 1 else ""
    print(f"\n{'giọng':28s}{'đúng':>10s}{'tỉ lệ':>8s}{cot_luot}{xat:>9s}"
          "   phụ âm rụng")

    def _luot_cua(g: str) -> tuple[int, int]:
        sai = tong = 0
        for i in range(len(bo)):
            if i in moi_giong_sai:
                continue
            s, t = luot.get((g, i), (0, 0))
            sai, tong = sai + s, tong + t
        return sai, tong

    # Xếp theo điểm đa số trước, rồi tới số lượt hụt — hai giọng cùng điểm thì
    # giọng hụt ít lần hơn đứng trên.
    xep = sorted(diem.items(), key=lambda kv: (-kv[1][0], _luot_cua(kv[0])[0]))
    for giong, (dung, tong) in xep:
        # Liệt kê ĐÚNG âm đã rụng, không phải nhãn của câu: câu "nhà em ở gần
        # đây" thử cả nh và g, in nhãn "nh · g" thì đọc thành rụng cả hai.
        loi = [d.strip("-") for i in range(len(bo))
               if i not in moi_giong_sai
               for d in rung.get((giong, i), ())]
        tl = 100.0 * dung / max(tong, 1)
        hut = [d.strip("-") for i in range(len(bo))
               if i not in moi_giong_sai
               for d in chap_chon.get((giong, i), ())]
        cot_xat = ""
        if lang == "vi":
            # Đo âm xát cũng phải lặp: VITS đọc khác nhau mỗi lần.
            mau = []
            for _ in range(max(1, min(lap, 3))):
                try:
                    m = _manh_am_xat(giong)
                except Exception:
                    m = None
                if m is not None:
                    mau.append(m)
            cot_xat = (f"{sum(mau) / len(mau):>9.1f}" if mau
                       else f"{'—':>9s}")
        duoi = ", ".join(loi) if loi else "—"
        if hut:
            duoi += f"   (chập chờn: {', '.join(hut)})"
        o_luot = ""
        if lap > 1:
            sai_l, tong_l = _luot_cua(giong)
            o_luot = f"{f'{sai_l}/{tong_l}':>12s}"
        print(f"{giong:28s}{dung:>6d}/{tong:<3d}{tl:>7.0f}%{o_luot}{cot_xat}"
              f"   {duoi}")
    if moi_giong_sai:
        print(f"\nCâu mà ≥{nguong}/{len(giong_ds)} giọng đều sai — KHÔNG dùng để "
              "xếp hạng giọng cùng họ.\nHoặc STT nghe không ra, hoặc cả họ model "
              "đọc kém; phải đo một họ giọng khác mới phân biệt được:")
        for i in sorted(moi_giong_sai):
            print(f"  \"{bo[i][0]}\" (thử {bo[i][2]})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tieng", nargs="+", choices=[*BO_TEST, "all"])
    ap.add_argument("--giong", default="",
                    help="giới hạn danh sách giọng (vi/en) hoặc sid (zh/ja/ko), "
                         "cách nhau bằng dấu phẩy")
    ap.add_argument("--buoc", default="",
                    help="ja/ko: thử các num_steps này (ví dụ 4,16)")
    ap.add_argument("--lap", type=int, default=1,
                    help="đọc lại mỗi câu bao nhiêu lần rồi lấy đa số "
                         "(VITS đọc ngẫu nhiên nên 1 lần không đủ kết luận)")
    a = ap.parse_args()
    tiengs = list(BO_TEST) if "all" in a.tieng else a.tieng
    buocs = [int(x) for x in a.buoc.split(",") if x.strip()] or [0]
    for lang in tiengs:
        ds = ([x.strip() for x in a.giong.split(",") if x.strip()]
              or _giong_can_do(lang))
        if not ds:
            print(f"\n=== tiếng {lang}: chưa tải giọng nào — bỏ qua")
            continue
        for b in (buocs if lang in ("ja", "ko") else [0]):
            do_mot_tieng(lang, ds, b, max(1, a.lap))


if __name__ == "__main__":
    main()
