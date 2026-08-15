#!/usr/bin/env python3
"""Kiểm chất lượng NGHE (STT) trên tiếng người thật kèm bản chữ đúng.

**Vì sao phải có bộ tiếng người, không đo bằng TTS.** Bệ đo phát âm
(``kiem_phat_am.py``) cho TTS đọc rồi lấy STT nghe lại. Vòng đó **không tự chứng
minh được**: STT nghe kém một phụ âm thì mọi giọng đọc đều bị nó chấm là rụng âm,
mà bảng kết quả trông vẫn thuyết phục. Muốn biết chính STT sai bao nhiêu thì phải
có tiếng NGƯỜI đọc kèm bản chữ đúng — ở đây dùng FLEURS (Google, bộ công khai,
có cả năm tiếng nên đo so sánh ngang nhau được).

Chuyện này quan trọng độc lập với TTS: STT là thứ sinh ra PHỤ ĐỀ và đọc TIN
THOẠI. TTS đọc nhẹ một phụ âm thì người nghe còn đoán ra, còn STT nghe sai một
chữ thì phụ đề in thẳng chữ sai vào phim.

Ngoài tỉ lệ sai chữ (WER) và sai ký tự (CER), bảng còn đếm **phụ âm đầu nào hay
bị nghe lệch thành phụ âm nào** — đó là thứ trả lời được câu "STT có rụng phụ âm
giống TTS không", và cũng là thứ cho biết bảng chấm TTS có bị quan toà làm lệch.

**Số nền đo ngày 14/08/2026** (150 bản thu mỗi tiếng, ~24–33 phút tiếng nói),
để lần sau đổi model thì có mốc so::

    tiếng   sai từ   sai ký tự   không nghe ra chữ nào
    vi        9,3%        6,5%   0
    en       16,6%       15,0%   11/150  (7%)
    zh          —        13,6%   0
    ja          —         9,8%   0
    ko          —        55,5%   67/150  (45%)

Cùng ngày, cùng 150 bản thu đó, đo qua ``--gpu`` (faster-whisper large-v3 trên
RTX 2060 Super) — không tiếng nào còn bỏ trắng bản nào::

    tiếng   sai từ   sai ký tự   không nghe ra chữ nào
    vi        8,4%        5,0%   0
    en        4,5%        2,7%   0
    zh          —        10,0%   0
    ja          —         5,1%   0
    ko          —         2,8%   0

Hai chỗ cần biết trước khi tin mấy con số này:

- **Tiếng Hàn 55,5% KHÔNG phải model hỏng, mà là lệch miền.** Model
  `korean-2024-06-24` học trên KsponSpeech — tiếng nói hội thoại câu ngắn — còn
  FLEURS là giọng đọc bản tin câu dài. Đã kiểm: nó đọc đúng bộ thử của chính nó
  (3/4 câu khớp từng chữ), không phải giới hạn độ dài (cắt còn 10 giây vẫn rỗng),
  và không phải do int8 (bản fp32 cho kết quả y hệt). Vậy với thoại phim và tin
  nhắn thoại thì khá hơn số này nhiều; với bản tin đọc thì đừng tin nó.
- **Phần lớn lỗi tiếng Việt là chọn CHỮ đồng âm, không phải nghe sai ÂM:** tr→ch,
  s→x, gi→d, r→d, c→k. Với phụ đề thì vẫn là chữ sai in lên phim, nhưng đó là lỗi
  chính tả chứ không phải mất phát âm.

Tải bộ đo (một lần, ~200–550 MB mỗi tiếng)::

    cd /app/data/fleurs
    curl -sLO https://huggingface.co/datasets/google/fleurs/resolve/main/data/vi_vn/test.tsv
    curl -sL .../data/vi_vn/audio/test.tar.gz | tar -xz

Chạy::

    docker exec c2a /app/.venv/bin/python /app/scripts/kiem_nghe.py vi --so 200
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kiem_phat_am import _am_dau, _bo_thanh, _chuan  # noqa: E402
from services.voice import engines as eng  # noqa: E402

FLEURS_DIR = Path("/app/data/fleurs")
# Mã tiếng của ta → tên thư mục FLEURS.
MA_FLEURS = {"vi": "vi_vn", "en": "en_us", "zh": "cmn_hans_cn",
             "ja": "ja_jp", "ko": "ko_kr"}
_A_DONG = ("zh", "ja", "ko")


def _doc_tsv(duong: Path) -> list[tuple[str, str]]:
    """(tên tệp wav, bản chữ đúng) — FLEURS: cột 2 là tệp, cột 3 là câu chữ.

    Bộ này có nhiều người đọc CÙNG một câu nên tên tệp lặp câu; giữ nguyên,
    mỗi bản thu là một phép thử riêng.
    """
    ra: list[tuple[str, str]] = []
    for dong in duong.read_text(encoding="utf-8").splitlines():
        cot = dong.split("\t")
        if len(cot) >= 3 and cot[1].endswith(".wav"):
            ra.append((cot[1], cot[2]))
    return ra


def _nghe_gpu(tep: Path, lang: str, url: str, batch: int = 2) -> str:
    """Nghe bằng dịch vụ faster-whisper trên máy GPU (fw-nghe), trả bản chữ.

    Có mặt ở đây để so ĐÚNG cùng bộ dữ liệu với đường local — chọn đường nghe
    cho phụ đề phải dựa vào số đo trên cùng bản thu, không dựa vào phỏng đoán.
    """
    import requests

    with tep.open("rb") as f:
        r = requests.post(f"{url.rstrip('/')}/nghe",
                          files={"tep": (tep.name, f, "audio/wav")},
                          data={"lang": lang, "batch": str(batch)}, timeout=600)
    r.raise_for_status()
    return " ".join(d.get("chu") or "" for d in (r.json().get("doan") or []))


def _gpu_nhiet(url: str) -> tuple[float, float] | None:
    """(nhiệt độ °C, tải %) của card bên máy GPU — None nếu nó không khai.

    Đo dài mà không nhìn nhiệt độ thì dễ đo nhầm: card nóng tới ngưỡng sẽ tự hạ
    xung, và bảng kết quả vẫn ra số bình thường như thể không có gì. Dịch vụ
    fw-nghe bản cũ chưa trả khoá "gpu" thì hàm này trả None và bảng im lặng như
    trước, không hỏng.
    """
    import requests

    try:
        d = requests.get(f"{url.rstrip('/')}/health", timeout=5).json()
        g = d.get("gpu") or {}
        return float(g["nhiet_do_c"]), float(g["tai_pct"])
    except Exception:
        return None


def _tu(s: str, lang: str) -> list[str]:
    """Tách thành đơn vị để so: tiếng Trung/Nhật/Hàn tính theo KÝ TỰ."""
    chuan = _chuan(s)
    if lang in _A_DONG:
        return [c for c in chuan if not c.isspace()]
    return chuan.split()


# Chữ chỉ SỐ của từng tiếng. Dùng để đếm riêng phần lỗi chỉ là KHÁC CÁCH VIẾT
# số, không phải nghe sai: bản gốc FLEURS viết "Twentieth century" còn máy viết
# "20th century" — đọc lên y hệt, phụ đề in ra cũng không sai, nhưng thước đo
# tính là sai trọn một từ. Cùng loại với chuyện chữ Hán và kana bên bệ đo phát
# âm: chấm chính tả trong khi đang muốn đo cái nghe.
_SO_CHU: dict[str, frozenset[str]] = {
    "en": frozenset((
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
        "thirty forty fifty sixty seventy eighty ninety hundred thousand "
        "million billion trillion first second third fourth fifth sixth "
        "seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
        "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth "
        "thirtieth fortieth fiftieth hundredth thousandth millionth"
    ).split()),
    "vi": frozenset((
        "không một mốt hai ba bốn tư năm lăm sáu bảy tám chín mười mươi trăm "
        "nghìn ngàn triệu tỷ tỉ"
    ).split()),
}
# Chữ số của ba tiếng viết bằng chữ vuông và Hàn — so theo KÝ TỰ nên liệt kê
# từng chữ một.
_SO_KY_TU = frozenset("0123456789〇零一二三四五六七八九十百千万萬億"
                      "영일이삼사오육칠팔구십백천만억")


def _co_so(don_vi: str, lang: str) -> bool:
    """Đơn vị này là số (chữ số, hay chữ đọc số) hay không."""
    if any(c.isdigit() for c in don_vi):
        return True
    if lang in _A_DONG:
        return don_vi in _SO_KY_TU
    return _bo_thanh(don_vi) in _SO_CHU.get(lang, frozenset())


def _khoang_cach(a: list[str], b: list[str]) -> int:
    """Khoảng cách sửa (Levenshtein) giữa hai dãy — lõi tính WER/CER."""
    truoc = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        nay = [i]
        for j, y in enumerate(b, 1):
            nay.append(min(truoc[j] + 1, nay[j - 1] + 1,
                           truoc[j - 1] + (x != y)))
        truoc = nay
    return truoc[-1]


def _lech_phu_am(dung: list[str], nghe: list[str]) -> list[tuple[str, str]]:
    """Cặp (âm đầu đúng, âm đầu nghe ra) ở những từ bị nghe thành từ khác.

    Chỉ xét khối 'replace' cùng độ dài: ở đó từ thứ i tương ứng từ thứ i, nên
    quy được lỗi về từng phụ âm. Khối thêm/bớt từ thì không quy được, bỏ qua.
    """
    ra: list[tuple[str, str]] = []
    so = difflib.SequenceMatcher(a=dung, b=nghe, autojunk=False)
    for viec, i1, i2, j1, j2 in so.get_opcodes():
        if viec != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for k in range(i2 - i1):
            a = _am_dau(_bo_thanh(dung[i1 + k]))
            b = _am_dau(_bo_thanh(nghe[j1 + k]))
            if a != b:
                ra.append((a or "(không)", b or "(không)"))
    return ra


def _rec_thu(duong: Path, kieu: str, luong: int = 4, lang: str = ""):
    """Dựng bộ nhận dạng từ MỘT thư mục model bất kỳ, để ĐO THỬ model mới.

    Cố ý không đi qua ``services.voice.engines``: ở đó model gắn với cấu hình
    đang chạy thật, nên muốn thử model mới thì phải đổi cấu hình của máy đang
    phục vụ rồi mới đo được — làm ngược. Ở đây đo xong mới quyết định đổi.
    """
    import sherpa_onnx

    def _mot(mau: str) -> str:
        hits = sorted(duong.glob(mau))
        if not hits:
            raise SystemExit(f"thiếu file khớp '{mau}' trong {duong}")
        return str(hits[0])

    if kieu == "sense_voice":
        # Khai đúng tiếng thay vì để model tự dò: ta biết chắc tiếng của bộ đo,
        # còn tự dò thì thêm một chỗ hỏng được mà lại tính vào điểm của model.
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=_mot("model*.onnx"), tokens=str(duong / "tokens.txt"),
            num_threads=luong, language=lang, use_itn=True)
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=_mot("encoder*.onnx"), decoder=_mot("decoder*.onnx"),
        joiner=_mot("joiner*.onnx"), tokens=str(duong / "tokens.txt"),
        num_threads=luong, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search")


def _nghe_rec(rec, wav16: bytes) -> str:
    import numpy as np

    rate, _w, _k, pcm = eng._wav_parts(wav16)
    st = rec.create_stream()
    st.accept_waveform(rate, np.frombuffer(pcm, dtype=np.int16)
                       .astype(np.float32) / 32768.0)
    rec.decode_stream(st)
    return str(st.result.text or "")


def do_mot_tieng(lang: str, so: int, thu_muc: Path, gpu: str = "",
                 rec=None) -> None:
    ma = MA_FLEURS[lang]
    tsv = thu_muc / f"{ma}.test.tsv"
    if not tsv.is_file():
        tsv = thu_muc / ma / "test.tsv"
    if not tsv.is_file():
        print(f"=== tiếng {lang}: chưa có {ma}.test.tsv trong {thu_muc} — bỏ qua")
        return
    cap = _doc_tsv(tsv)
    # Dựng bảng tên → đường dẫn MỘT lần: quét lại thư mục cho từng câu thì
    # 857 bản thu thành 857 lượt quét.
    kho = {t.name: t for t in (thu_muc / ma).rglob("*.wav")}
    print(f"\n=== NGHE tiếng {lang} · bộ FLEURS {ma} · {len(cap)} bản thu "
          f"({len(kho)} tệp trên đĩa), đo {min(so, len(cap))} bản"
          + (f" · qua GPU {gpu}" if gpu else
             " · model ĐANG THỬ" if rec is not None else " · model local"))

    tong_tu = tong_loi = 0
    tong_kt = tong_loi_kt = 0
    tong_tu_ks = tong_loi_ks = 0   # ks = khi bỏ mọi đơn vị có số ra khỏi cả hai bên
    lech: dict[tuple[str, str], int] = {}
    xong = bo = rong = 0
    giay = 0.0
    nhiet: list[tuple[float, float]] = []   # (°C, tải %) lấy mỗi 25 bản thu
    for ten, chu_dung in cap:
        if xong >= so:
            break
        tep = kho.get(ten)
        if tep is None:
            bo += 1
            continue
        try:
            # KHÔNG mở bằng module `wave`: FLEURS lưu WAV dạng số thực IEEE
            # (format 3) mà `wave` chỉ đọc được PCM nguyên. Bộ chuyển của dự
            # án gọi ffmpeg nên nhận mọi định dạng, và STT cũng nhận cùng bytes.
            wav16 = eng.to_wav_16k_mono(tep.read_bytes(), tep.suffix)
            rate, width, kenh, du_lieu = eng._wav_parts(wav16)
            giay += len(du_lieu) / float(max(rate * width * kenh, 1))
        except Exception as exc:
            bo += 1
            if bo <= 5:      # đủ để thấy nguyên nhân, khỏi tràn 857 dòng
                print(f"  LỖI đọc tệp {ten}: {str(exc)[:110]}")
            continue
        try:
            ra = (_nghe_gpu(tep, lang, gpu) if gpu
                  else _nghe_rec(rec, wav16) if rec is not None
                  else eng.transcribe(wav16, lang=lang))
        except Exception:
            # "Không nghe ra chữ nào" phải tính là SAI TRỌN, không được bỏ qua:
            # bỏ qua thì con số đẹp lên đúng ở những bản khó nhất, mà với người
            # làm phụ đề thì mất trắng một dòng là lỗi nặng nhất.
            ra = ""
        if not ra.strip():
            rong += 1
        dung, nghe = _tu(chu_dung, lang), _tu(ra, lang)
        tong_tu += len(dung)
        tong_loi += _khoang_cach(dung, nghe)
        kt_dung = list(_chuan(chu_dung).replace(" ", ""))
        kt_nghe = list(_chuan(ra).replace(" ", ""))
        tong_kt += len(kt_dung)
        tong_loi_kt += _khoang_cach(kt_dung, kt_nghe)
        # Cùng phép so, nhưng bỏ mọi đơn vị có số ra khỏi CẢ HAI bên. Chênh
        # lệch giữa hai con số là phần lỗi nằm ở chỗ viết số, tức phần mà đổi
        # model sẽ KHÔNG chữa được.
        ks_dung = [t for t in dung if not _co_so(t, lang)]
        ks_nghe = [t for t in nghe if not _co_so(t, lang)]
        tong_tu_ks += len(ks_dung)
        tong_loi_ks += _khoang_cach(ks_dung, ks_nghe)
        if lang not in _A_DONG:
            for cap_am in _lech_phu_am(dung, nghe):
                lech[cap_am] = lech.get(cap_am, 0) + 1
        xong += 1
        if gpu and xong % 25 == 0:
            do = _gpu_nhiet(gpu)
            if do is not None:
                nhiet.append(do)
                print(f"  [{xong} bản] GPU {do[0]:.0f}°C · tải {do[1]:.0f}%"
                      + ("   ⚠ NÓNG — card sắp tự hạ xung" if do[0] >= 80 else ""))
        if xong <= 3:
            print(f"  ví dụ {xong}: đúng  “{chu_dung[:70]}”")
            print(f"            nghe  “{ra[:70]}”")

    wer = 100.0 * tong_loi / max(tong_tu, 1)
    cer = 100.0 * tong_loi_kt / max(tong_kt, 1)
    print(f"\n  {xong} bản thu ({giay / 60:.1f} phút tiếng nói)"
          + (f", bỏ {bo} bản không đọc được tệp" if bo else ""))
    if lang not in _A_DONG:      # zh/ja/ko tính theo ký tự nên hai số trùng nhau
        print(f"  sai từ:     {wer:5.1f}%   ({tong_loi}/{tong_tu})")
    print(f"  sai ký tự:  {cer:5.1f}%   ({tong_loi_kt}/{tong_kt})")
    don_vi = "ký tự" if lang in _A_DONG else "từ"
    ks = 100.0 * tong_loi_ks / max(tong_tu_ks, 1)
    print(f"  bỏ chỗ có SỐ: sai {don_vi} {ks:5.1f}%   "
          f"({tong_loi_ks}/{tong_tu_ks}) — chênh với dòng trên là phần lỗi chỉ "
          "do KHÁC CÁCH VIẾT số")
    if rong:
        print(f"  KHÔNG NGHE RA CHỮ NÀO: {rong}/{xong} bản "
              f"({100.0 * rong / max(xong, 1):.0f}%) — đã tính là sai trọn")
    if nhiet:
        nong = max(t for t, _ in nhiet)
        print(f"  GPU: nóng nhất {nong:.0f}°C, tải trung bình "
              f"{sum(u for _, u in nhiet) / len(nhiet):.0f}%"
              + ("  ⚠ đã chạm ngưỡng hạ xung — số đo có thể là đo card bị bóp"
                 if nong >= 80 else ""))
    if lech:
        print("\n  Phụ âm đầu hay bị nghe lệch (đúng → nghe ra, số lần):")
        for (a, b), n in sorted(lech.items(), key=lambda kv: -kv[1])[:15]:
            print(f"    {a:>8s} → {b:<8s} {n}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tieng", nargs="+", choices=[*MA_FLEURS, "all"])
    ap.add_argument("--so", type=int, default=200, help="số bản thu mỗi tiếng")
    ap.add_argument("--thu-muc", default=str(FLEURS_DIR))
    ap.add_argument("--gpu", default="",
                    help="đo qua dịch vụ faster-whisper thay vì model local, "
                         "ví dụ http://172.16.10.220:5002")
    ap.add_argument("--model", default="",
                    help="ĐO THỬ model ở thư mục này thay vì model đang cấu "
                         "hình — không đổi gì của máy đang chạy")
    ap.add_argument("--kieu", default="transducer",
                    choices=["transducer", "sense_voice"],
                    help="loại model của --model")
    ap.add_argument("--luong", type=int, default=4,
                    help="số luồng cho --model (mặc định 4, khớp taskset 0-3)")
    a = ap.parse_args()
    tiengs = list(MA_FLEURS) if "all" in a.tieng else a.tieng
    for lang in tiengs:
        rec = None
        if a.model.strip():
            # Dựng lại theo TỪNG tiếng: SenseVoice nhận tham số tiếng lúc dựng.
            rec = _rec_thu(Path(a.model.strip()), a.kieu, max(1, a.luong), lang)
            print(f"\n[đo thử] model {a.model} · kiểu {a.kieu} · tiếng {lang}")
        do_mot_tieng(lang, max(1, a.so), Path(a.thu_muc), a.gpu.strip(), rec)


if __name__ == "__main__":
    main()
