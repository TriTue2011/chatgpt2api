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
        ("the zoo has six animals", ("zoo", "six"), "z · ks"),
        ("nine numbers and one name", ("nine", "numbers", "name"), "n · m"),
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
    # Viết bằng chữ Hán như văn bản thật — đọc sai chữ Hán cũng là một lỗi cần
    # thấy, vì bản dịch đưa vào TTS chính là văn bản có chữ Hán.
    "ja": (
        ("今日はいい天気ですね", ("今日", "天気"), "k · t"),
        ("私は日本語を勉強します", ("日本語", "勉強"), "n · b"),
        ("時間がありません", ("時間",), "j"),
        ("写真を撮ってください", ("写真",), "sh"),
        ("電話番号を教えて", ("電話", "番号"), "d · b"),
        ("駅はどこですか", ("駅",), "e"),
        ("音楽を聞きます", ("音楽",), "ng"),
        ("三つの質問", ("質問",), "sh · ts"),
        ("会社に行きます", ("会社",), "k · sh"),
        ("よろしくお願いします", ("願い",), "y · n"),
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
    """
    r = _chuan(ra)
    if lang in _A_DONG:
        return _chuan(dich).replace(" ", "") in r.replace(" ", "")
    tu = [_bo_thanh(t) for t in r.split()]
    if dich.endswith("-"):
        return any(_am_dau(t) == dich[:-1] for t in tu)
    if dich.startswith("-"):
        return any(_am_cuoi(t) == dich[1:] for t in tu)
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


def do_mot_tieng(lang: str, giong_ds: list[str], buoc: int = 0) -> None:
    bo = BO_TEST[lang]
    tong_dich = sum(len(t[1]) for t in bo)
    print(f"\n=== tiếng {lang} · {len(giong_ds)} giọng × {len(bo)} câu "
          f"({tong_dich} âm tiết cần nghe lại)"
          + (f" · num_steps={buoc}" if buoc else ""))
    # (giọng, câu) → những âm tiết KHÔNG nghe lại được
    rung: dict[tuple[str, int], list[str]] = {}
    diem: dict[str, tuple[int, int]] = {}
    for giong in giong_ds:
        dung = 0
        for i, (cau, dich, _nhan) in enumerate(bo):
            try:
                wav = _doc(cau, giong, lang, buoc)
                ra = eng.transcribe(wav, lang=lang)
            except Exception as exc:
                print(f"  {giong}: LỖI {str(exc)[:140]}")
                rung[(giong, i)] = list(dich)
                continue
            mat = [d for d in dich if not _nghe_thay(d, ra, lang)]
            dung += len(dich) - len(mat)
            if mat:
                rung[(giong, i)] = mat
                print(f"  {giong:26s} [{'/'.join(mat)}] ← \"{ra[:60]}\"")
        diem[giong] = (dung, tong_dich)

    # Câu mọi giọng đều sai = STT không nghe được, không tính là lỗi giọng.
    moi_giong_sai = {
        i for i in range(len(bo))
        if all((g, i) in rung for g in giong_ds)
    }
    xat = "  âm xát" if lang == "vi" else ""
    print(f"\n{'giọng':28s}{'đúng':>10s}{'tỉ lệ':>8s}{xat:>9s}   phụ âm rụng")
    xep = sorted(diem.items(), key=lambda kv: -kv[1][0])
    for giong, (dung, tong) in xep:
        loi = [bo[i][2] for i in range(len(bo))
               if (giong, i) in rung and i not in moi_giong_sai]
        tl = 100.0 * dung / max(tong, 1)
        cot_xat = ""
        if lang == "vi":
            try:
                m = _manh_am_xat(giong)
            except Exception:
                m = None
            cot_xat = f"{m:>9.1f}" if m is not None else f"{'—':>9s}"
        print(f"{giong:28s}{dung:>6d}/{tong:<3d}{tl:>7.0f}%{cot_xat}   "
              + (", ".join(loi) if loi else "—"))
    if moi_giong_sai:
        print("\nCâu MỌI giọng đều sai — hạn chế của STT, không tính lỗi giọng:")
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
            do_mot_tieng(lang, ds, b)


if __name__ == "__main__":
    main()
