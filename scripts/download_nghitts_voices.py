#!/usr/bin/env python3
"""Tải giọng tiếng Việt NghiTTS về data/nghitts/ — KHÔNG nằm trong image.

Cùng nguyên tắc giọng Piper/Kokoro/VieNeu: code trong image, model ngoài volume.
Mỗi giọng ~64 MB, cả 19 giọng ~1,2 GB nên mặc định chỉ tải giọng mặc định.

    python scripts/download_nghitts_voices.py                  # giọng mặc định
    python scripts/download_nghitts_voices.py ngoc-ngan my-tam # vài giọng
    python scripts/download_nghitts_voices.py --all            # cả 19 (~1,2 GB)
    python scripts/download_nghitts_voices.py --list           # xem danh mục
    python scripts/download_nghitts_voices.py --check          # chỉ kiểm tra
    python scripts/download_nghitts_voices.py --espeak         # chỉ lo espeak-ng-data

Chọn giọng trong WebUI: id dạng "nghi:ngoc-huyen-moi", "nghi:my-tam"…

MỖI FILE ĐỀU ĐỐI CHIẾU SHA-256 đã ghim trong services/voice/nghitts_voices.py.
Nguồn tải là API công khai không có phiên bản, chủ trang thay file dưới cùng tên
lúc nào cũng được; băm lệch thì DỪNG chứ không ghi đè giọng đang chạy.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "nghitts"

# Nạp THẲNG file danh mục, không qua `from services.voice import ...`: import cả
# gói sẽ kéo theo services.config và bắt phải có CHATGPT2API_AUTH_KEY, trong khi
# script tải model cần chạy được trên máy trắng. nghitts_voices.py cố ý không
# import gì trong gói để cách này luôn đúng — đừng thêm import vào đó.
_spec = importlib.util.spec_from_file_location(
    "nghitts_voices", ROOT / "services" / "voice" / "nghitts_voices.py")
nv = importlib.util.module_from_spec(_spec)          # type: ignore[arg-type]
# @dataclass tra cứu sys.modules[cls.__module__] để dựng field — không đăng ký
# trước thì nạp module này ném AttributeError ngay tại dòng class.
sys.modules["nghitts_voices"] = nv
_spec.loader.exec_module(nv)                          # type: ignore[union-attr]

# espeak-ng-data lấy từ đúng gói piper mà Dockerfile đã dùng (băm ghim y hệt),
# không thêm nguồn ngoài nào. Dữ liệu này độc lập kiến trúc nên bản x86_64 dùng
# được cho cả máy ARM.
PIPER_URL = ("https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
             "piper_linux_x86_64.tar.gz")
PIPER_SHA256 = "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"
ESPEAK_NEED = ("phondata", "phontab", "vi_dict", "lang/aav/vi")
USER_AGENT = "chatgpt2api-voice-downloader/1.0"
ESPEAK_CANDIDATES = [
    DEST / "espeak-ng-data",
    ROOT / "data" / "kokoro" / "espeak-ng-data",
    Path("/opt/piper/espeak-ng-data"),
    Path("/usr/share/espeak-ng-data"),
    Path("/usr/lib/espeak-ng-data"),
]


def _show(path: Path) -> str:
    """Đường dẫn gọn để in. File tạm nằm ngoài gốc dự án nên phải chịu được cả
    trường hợp không quy về tương đối được."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(url: str, dest: Path, expect_sha: str, label: str) -> None:
    """Tải về file tạm, đối chiếu băm, rồi mới thay file thật (thay nguyên tử).

    Tải thẳng vào đích thì đứt mạng giữa chừng sẽ để lại file cụt mà lần chạy
    sau tưởng là đã có.

    Phải đặt User-Agent: nghitts.app đứng sau Cloudflare và trả 403 cho UA mặc
    định "Python-urllib" của urlretrieve.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        print(f"[tai] {label}")
        digest = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
            while True:
                block = resp.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                out.write(block)
        got = digest.hexdigest()
        if got != expect_sha:
            raise ValueError(
                f"SHA-256 lech cho {label}: nhan {got}, mong doi {expect_sha}")
        os.replace(tmp, dest)
        print(f"[ok]  {_show(dest)}")
    finally:
        tmp.unlink(missing_ok=True)


def _espeak_ok(base: Path) -> bool:
    try:
        return all((base / n).is_file() for n in ESPEAK_NEED)
    except OSError:
        return False


def _find_espeak() -> Path | None:
    for c in ESPEAK_CANDIDATES:
        if _espeak_ok(c):
            return c
    return None


def ensure_espeak() -> Path | None:
    """Bảo đảm có espeak-ng-data; thiếu thì rút từ gói piper về data/nghitts/."""
    found = _find_espeak()
    if found is not None:
        print(f"[co]  espeak-ng-data: {found}")
        return found
    print("[thieu] espeak-ng-data — rut tu goi piper (~26 MB)")
    target = DEST / "espeak-ng-data"
    with tempfile.TemporaryDirectory() as td:
        tgz = Path(td) / "piper.tar.gz"
        _fetch(PIPER_URL, tgz, PIPER_SHA256, "piper (chi lay espeak-ng-data)")
        with tarfile.open(tgz, "r:gz") as tar:
            members = [m for m in tar.getmembers()
                       if m.name.startswith("piper/espeak-ng-data/")]
            if not members:
                print("[LOI] goi piper khong co espeak-ng-data", file=sys.stderr)
                return None
            tar.extractall(td, members=members, filter="data")
        src = Path(td) / "piper" / "espeak-ng-data"
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
    if not _espeak_ok(target):
        print(f"[LOI] espeak-ng-data rut ra van thieu file: {target}", file=sys.stderr)
        return None
    print(f"[ok]  {_show(target)}")
    return target


def _write_tokens(voice_dir: Path) -> None:
    """Sinh tokens.txt từ phoneme_id_map trong model.onnx.json.

    NghiTTS không phát hành tokens.txt rời, nhưng sherpa-onnx bắt buộc phải có.
    """
    cfg = json.loads((voice_dir / nv.CONFIG_FILE).read_text(encoding="utf-8"))
    tokens = nv.tokens_from_config(cfg)
    out = voice_dir / nv.TOKENS_FILE
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            "".join(f"{tok} {i}\n" for i, tok in enumerate(tokens)), encoding="utf-8")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"[ok]  {_show(out)} ({len(tokens)} token)")


def voice_complete(voice) -> bool:
    d = DEST / voice.id
    return all((d / n).is_file()
               for n in (nv.MODEL_FILE, nv.CONFIG_FILE, nv.TOKENS_FILE))


def download_voice(voice) -> bool:
    """Tải một giọng; trả True nếu sau cùng đủ file. Đã đủ thì bỏ qua."""
    voice_dir = DEST / voice.id
    if voice_complete(voice):
        print(f"[bo qua] {voice.id} — da co du file")
        return True
    print(f"--- {voice.id} ({voice.name}, {voice.language}) ---")
    for remote, local, sha in voice.artifacts:
        dest = voice_dir / local
        if dest.is_file() and _sha256(dest) == sha:
            print(f"[co]  {_show(dest)}")
            continue
        url = f"{nv.BASE_URL}/{urllib.parse.quote(remote, safe='')}"
        try:
            _fetch(url, dest, sha, f"{remote} → {_show(dest)}")
        except Exception as exc:
            print(f"[LOI] {voice.id}: {exc}", file=sys.stderr)
            return False
    try:
        _write_tokens(voice_dir)
    except Exception as exc:
        print(f"[LOI] {voice.id}: khong sinh duoc tokens.txt — {exc}", file=sys.stderr)
        return False
    return voice_complete(voice)


def cmd_list() -> int:
    espeak = _find_espeak()
    print(f"espeak-ng-data: {espeak or 'CHUA CO (chay voi --espeak)'}\n")
    print(f"{'ma giong':<24} {'ten hien thi':<24} {'giong':<16} tai ve")
    for v in nv.VOICES:
        mark = "co" if voice_complete(v) else "-"
        default = " (mac dinh)" if v.id == nv.DEFAULT_ID else ""
        print(f"{v.id:<24} {v.name:<24} {v.language:<16} {mark}{default}")
    return 0


def cmd_check() -> int:
    have = [v.id for v in nv.VOICES if voice_complete(v)]
    espeak = _find_espeak()
    print(f"giong da tai : {len(have)}/{len(nv.VOICES)}" + (f" — {', '.join(have)}" if have else ""))
    print(f"espeak-ng-data: {espeak or 'THIEU'}")
    return 0 if (have and espeak) else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voices", nargs="*", help="mã giọng cần tải (trống = giọng mặc định)")
    ap.add_argument("--all", action="store_true", help=f"tải cả {len(nv.VOICES)} giọng (~1,2 GB)")
    ap.add_argument("--list", action="store_true", help="liệt kê danh mục rồi thoát")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra rồi thoát")
    ap.add_argument("--espeak", action="store_true", help="chỉ lo espeak-ng-data rồi thoát")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.check:
        return cmd_check()
    if args.espeak:
        return 0 if ensure_espeak() is not None else 1

    if args.all:
        wanted = list(nv.VOICES)
    elif args.voices:
        wanted = []
        for vid in args.voices:
            v = nv.get(vid)
            if v is None:
                print(f"[LOI] khong co ma giong '{vid}' — xem --list", file=sys.stderr)
                return 2
            wanted.append(v)
    else:
        wanted = [nv.BY_ID[nv.DEFAULT_ID]]

    if ensure_espeak() is None:
        print("[LOI] khong co espeak-ng-data — NghiTTS khong doc duoc", file=sys.stderr)
        return 1

    failed = [v.id for v in wanted if not download_voice(v)]
    done = len(wanted) - len(failed)
    print(f"\nXong: {done}/{len(wanted)} giọng." if not failed
          else f"\nXong: {done}/{len(wanted)} giọng. HỎNG: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
