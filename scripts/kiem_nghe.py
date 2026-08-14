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


def _tu(s: str, lang: str) -> list[str]:
    """Tách thành đơn vị để so: tiếng Trung/Nhật/Hàn tính theo KÝ TỰ."""
    chuan = _chuan(s)
    if lang in _A_DONG:
        return [c for c in chuan if not c.isspace()]
    return chuan.split()


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


def do_mot_tieng(lang: str, so: int, thu_muc: Path, gpu: str = "") -> None:
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
          + (f" · qua GPU {gpu}" if gpu else " · model local"))

    tong_tu = tong_loi = 0
    tong_kt = tong_loi_kt = 0
    lech: dict[tuple[str, str], int] = {}
    xong = bo = rong = 0
    giay = 0.0
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
        if lang not in _A_DONG:
            for cap_am in _lech_phu_am(dung, nghe):
                lech[cap_am] = lech.get(cap_am, 0) + 1
        xong += 1
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
    if rong:
        print(f"  KHÔNG NGHE RA CHỮ NÀO: {rong}/{xong} bản "
              f"({100.0 * rong / max(xong, 1):.0f}%) — đã tính là sai trọn")
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
    a = ap.parse_args()
    tiengs = list(MA_FLEURS) if "all" in a.tieng else a.tieng
    for lang in tiengs:
        do_mot_tieng(lang, max(1, a.so), Path(a.thu_muc), a.gpu.strip())


if __name__ == "__main__":
    main()
