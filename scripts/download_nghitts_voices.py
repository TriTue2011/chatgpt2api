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
    python scripts/download_nghitts_voices.py --upstream ...   # lấy từ nghitts.app

Chọn giọng trong WebUI: id dạng "nghi:ngoc-huyen-moi", "nghi:my-tam"…

HAI NGUỒN, giống cách download_stt_model.py làm với model Zipformer:

  1. **GitHub Release** của chính repo này (mặc định) — bản gương do ta giữ.
     Repo public nên tải thẳng bằng URL, không cần `gh` trên máy đích. Không
     phụ thuộc trang nguồn còn sống hay có đổi file hay không.
  2. **nghitts.app** (`--upstream`) — nguồn gốc, dùng khi dựng lại bản gương
     hoặc khi Release chưa có giọng đó.

MỖI FILE ĐỀU ĐỐI CHIẾU SHA-256 đã ghim trong services/voice/nghitts_voices.py,
cho cả hai nguồn. Nguồn gốc là API công khai không có phiên bản, chủ trang thay
file dưới cùng tên lúc nào cũng được; băm lệch thì DỪNG chứ không ghi đè giọng
đang chạy. Bản gương trên Release cũng kiểm băm y hệt nên không có nguồn nào
được tin sẵn.

Model NghiTTS xuất ra KHÔNG có metadata ONNX nên sherpa-onnx từ chối nạp; sau
khi tải, script vá 7 trường metadata vào file (xem nghitts_voices.sherpa_metadata)
và ghi một dấu ghi nhận cạnh đó. Vì vậy băm của model.onnx trên đĩa KHÁC băm đã
ghim — đó là bình thường, dấu ghi nhận mới là thứ để đối chiếu.

Dựng lại bản gương trên Release (chỉ làm khi thêm/đổi giọng) — bản gương phải là
bản GỐC chưa vá:

    python scripts/download_nghitts_voices.py --all --upstream --no-prepare --dest /tmp/guong
    python scripts/download_nghitts_voices.py --publish --dest /tmp/guong
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "nghitts"

# Bản gương trên Release của chính repo này — giống hệt cách model Zipformer
# được giữ (xem download_stt_model.py). Tên asset đặt theo MÃ giọng chứ không
# theo tên hiển thị: GitHub đổi khoảng trắng trong tên asset thành dấu chấm nên
# "Ngọc Huyền (mới).onnx" tải về sẽ ra một cái tên khác hẳn.
RELEASE_REPO = os.environ.get("C2A_REPO", "TriTue2011/chatgpt2api")
RELEASE_TAG = "nghitts-voices-v1"

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


def _espeak_candidates() -> list[Path]:
    """Nơi tìm espeak-ng-data, theo thứ tự ưu tiên.

    Tính lúc GỌI chứ không phải lúc nạp module: `--dest` đổi DEST sau khi module
    đã nạp, dựng sẵn danh sách sẽ trỏ nhầm về thư mục mặc định.
    """
    return [
        DEST / "espeak-ng-data",
        ROOT / "data" / "kokoro" / "espeak-ng-data",
        Path("/opt/piper/espeak-ng-data"),
        Path("/usr/share/espeak-ng-data"),
        Path("/usr/lib/espeak-ng-data"),
    ] + sorted(Path("/usr/lib").glob("*-linux-gnu/espeak-ng-data"))


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
    for c in _espeak_candidates():
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


def _marker_path(voice_dir: Path) -> Path:
    return voice_dir / nv.PREPARED_FILE


def _prepared_ok(voice_dir: Path, source_sha: str) -> bool:
    """Model đã vá metadata và vẫn đúng bản đó chưa.

    So kích thước + mtime thay vì băm lại: băm một đồ hình 60 MB cho mỗi giọng,
    mỗi lần chạy, là quá đắt mà chẳng thêm bảo đảm nào — file bị sửa lén thì
    mtime cũng đổi.
    """
    model = voice_dir / nv.MODEL_FILE
    marker = _marker_path(voice_dir)
    if not model.is_file() or not marker.is_file():
        return False
    try:
        rec = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    st = model.stat()
    return (rec.get("source_sha256") == source_sha
            and rec.get("output_size") == st.st_size
            and rec.get("output_mtime_ns") == st.st_mtime_ns)


def _prepare_model(voice_dir: Path, source_sha: str) -> None:
    """Vá metadata vào model.onnx để sherpa-onnx nạp được. Chạy lại vô hại.

    Model gốc KHÔNG có metadata nên sherpa-onnx từ chối nạp; xem
    nghitts_voices.sherpa_metadata. Ghi ra file tạm rồi thay nguyên tử, và lưu
    băm của BẢN GỐC vào dấu ghi nhận — nhờ vậy lần chạy sau biết file hiện tại
    ứng với bản gốc nào mà khỏi tải lại.
    """
    if _prepared_ok(voice_dir, source_sha):
        return
    model = voice_dir / nv.MODEL_FILE
    cfg = json.loads((voice_dir / nv.CONFIG_FILE).read_text(encoding="utf-8"))
    meta = nv.encode_onnx_metadata(nv.sherpa_metadata(cfg))

    got = _sha256(model)
    if got != source_sha:
        # Đã vá rồi mà mất dấu ghi nhận (vd xoá nhầm) — vá tiếp là hỏng file.
        raise ValueError(
            f"{_show(model)} khong khop ban goc (bam {got}). Xoa thu muc giong "
            f"nay roi tai lai.")
    tmp = model.with_name(f".{model.name}.{os.getpid()}.tmp")
    try:
        with model.open("rb") as src, tmp.open("wb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
            out.write(meta)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, model)
    finally:
        tmp.unlink(missing_ok=True)

    st = model.stat()
    marker = _marker_path(voice_dir)
    mtmp = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
    try:
        mtmp.write_text(json.dumps({
            "source_sha256": source_sha,
            "output_size": st.st_size,
            "output_mtime_ns": st.st_mtime_ns,
            "metadata_bytes": len(meta),
        }, sort_keys=True), encoding="utf-8")
        os.replace(mtmp, marker)
    finally:
        mtmp.unlink(missing_ok=True)
    print(f"[va]  {_show(model)} +{len(meta)} byte metadata cho sherpa-onnx")


def voice_complete(voice) -> bool:
    d = DEST / voice.id
    return (all((d / n).is_file()
                for n in (nv.MODEL_FILE, nv.CONFIG_FILE, nv.TOKENS_FILE))
            and _prepared_ok(d, voice.model_sha256))


def _asset_name(voice, local_name: str) -> str:
    """Tên file trên Release: "ban-mai.onnx", "ban-mai.onnx.json"."""
    return f"{voice.id}{local_name[len('model'):]}"


def _has_gh() -> bool:
    return shutil.which("gh") is not None


def _fetch_release(voice, local: str, sha: str, dest: Path) -> None:
    """Lấy một file từ GitHub Release. Bản gương cũng kiểm băm — không nguồn nào
    được tin sẵn.

    Repo này public nên tải thẳng bằng URL, KHÔNG cần `gh` trên máy đích. `gh`
    chỉ cần khi ĐẨY bản gương lên (--publish).
    """
    asset = _asset_name(voice, local)
    url = (f"https://github.com/{RELEASE_REPO}/releases/download/"
           f"{RELEASE_TAG}/{urllib.parse.quote(asset)}")
    _fetch(url, dest, sha, f"{asset} ← Release {RELEASE_TAG}")


def download_voice(voice, upstream: bool = False, prepare: bool = True) -> bool:
    """Tải một giọng; trả True nếu sau cùng đủ file. Đã đủ thì bỏ qua."""
    voice_dir = DEST / voice.id
    if voice_complete(voice):
        print(f"[bo qua] {voice.id} — da co du file")
        return True
    print(f"--- {voice.id} ({voice.name}, {voice.language}) ---")
    for remote, local, sha in voice.artifacts:
        dest = voice_dir / local
        # Model đã vá metadata thì băm khác bản gốc — hỏi dấu ghi nhận, đừng so
        # băm rồi tưởng hỏng mà tải lại 64 MB.
        if local == nv.MODEL_FILE and prepare and _prepared_ok(voice_dir, sha):
            print(f"[co]  {_show(dest)} (da va metadata)")
            continue
        if dest.is_file() and _sha256(dest) == sha:
            print(f"[co]  {_show(dest)}")
            continue
        try:
            if upstream:
                url = f"{nv.BASE_URL}/{urllib.parse.quote(remote, safe='')}"
                _fetch(url, dest, sha, f"{remote} → {_show(dest)}")
            else:
                _fetch_release(voice, local, sha, dest)
        except Exception as exc:
            print(f"[LOI] {voice.id}: {exc}", file=sys.stderr)
            return False
    try:
        _write_tokens(voice_dir)
        if prepare:
            _prepare_model(voice_dir, voice.model_sha256)
    except Exception as exc:
        print(f"[LOI] {voice.id}: {exc}", file=sys.stderr)
        return False
    return voice_complete(voice) if prepare else True


def cmd_publish() -> int:
    """Đẩy các giọng đang có dưới thư mục đích lên Release làm bản gương.

    Chỉ dùng khi thêm/đổi giọng. Đối chiếu băm TRƯỚC khi đẩy để không bao giờ
    đưa một file hỏng lên làm nguồn chuẩn cho máy khác tải về.
    """
    if not _has_gh():
        print("Can GitHub CLI (gh) da `gh auth login`.", file=sys.stderr)
        return 1
    have = [v for v in nv.VOICES
            if (DEST / v.id / nv.MODEL_FILE).is_file()
            and (DEST / v.id / nv.CONFIG_FILE).is_file()]
    if not have:
        print(f"Khong co giong nao trong {DEST} de day len.", file=sys.stderr)
        return 1

    exists = subprocess.run(
        ["gh", "release", "view", RELEASE_TAG, "-R", RELEASE_REPO],
        capture_output=True, text=True).returncode == 0
    if not exists:
        print(f"[tao] release {RELEASE_TAG}")
        proc = subprocess.run(
            ["gh", "release", "create", RELEASE_TAG, "-R", RELEASE_REPO,
             "--title", "NghiTTS Vietnamese voices v1",
             "--notes", "Bản gương 19 giọng tiếng Việt NghiTTS (VITS 22,05 kHz) "
                        "cho scripts/download_nghitts_voices.py. Nguồn gốc: "
                        "https://nghitts.app. SHA-256 từng file ghim trong "
                        "services/voice/nghitts_voices.py.",
             "--latest=false"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"[LOI] tao release: {proc.stderr.strip()[:300]}", file=sys.stderr)
            return 1

    failed = []
    for v in have:
        for _remote, local, sha in v.artifacts:
            src = DEST / v.id / local
            got = _sha256(src)
            if got != sha:
                extra = (" — file nay da VA METADATA, ban guong phai la ban GOC; "
                         "dung `--all --upstream --no-prepare` vao mot thu muc rieng")
                print(f"[LOI] {_show(src)} bam lech ({got}) — BO QUA, khong day len"
                      + (extra if _marker_path(src.parent).is_file() else ""),
                      file=sys.stderr)
                failed.append(v.id)
                continue
            asset = _asset_name(v, local)
            with tempfile.TemporaryDirectory() as td:
                staged = Path(td) / asset          # gh lấy tên asset từ tên file
                shutil.copy2(src, staged)
                print(f"[day] {asset} ({src.stat().st_size / 1048576:.0f} MB)")
                proc = subprocess.run(
                    ["gh", "release", "upload", RELEASE_TAG, str(staged),
                     "-R", RELEASE_REPO, "--clobber"],
                    capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"[LOI] day {asset}: {proc.stderr.strip()[:200]}", file=sys.stderr)
                failed.append(v.id)
    print(f"\nDay len {RELEASE_TAG}: {len(have) - len(set(failed))}/{len(have)} giong.")
    return 1 if failed else 0


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
    global DEST      # phải khai trước MỌI lần dùng DEST trong hàm này
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voices", nargs="*", help="mã giọng cần tải (trống = giọng mặc định)")
    ap.add_argument("--all", action="store_true", help=f"tải cả {len(nv.VOICES)} giọng (~1,2 GB)")
    ap.add_argument("--list", action="store_true", help="liệt kê danh mục rồi thoát")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra rồi thoát")
    ap.add_argument("--espeak", action="store_true", help="chỉ lo espeak-ng-data rồi thoát")
    ap.add_argument("--upstream", action="store_true",
                    help="lấy từ nguồn gốc nghitts.app thay vì bản gương trên Release")
    ap.add_argument("--publish", action="store_true",
                    help=f"đẩy giọng đang có lên Release {RELEASE_TAG} (chỉ khi thêm/đổi giọng)")
    ap.add_argument("--no-prepare", action="store_true",
                    help="giữ model NGUYÊN BẢN, không vá metadata (dùng khi dựng bản gương)")
    ap.add_argument("--dest", default="", help=f"thư mục đích (mặc định {DEST})")
    args = ap.parse_args()

    if args.dest:
        DEST = Path(args.dest)

    if args.list:
        return cmd_list()
    if args.check:
        return cmd_check()
    if args.publish:
        return cmd_publish()
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

    failed = [v.id for v in wanted
              if not download_voice(v, args.upstream, not args.no_prepare)]
    done = len(wanted) - len(failed)
    print(f"\nXong: {done}/{len(wanted)} giọng." if not failed
          else f"\nXong: {done}/{len(wanted)} giọng. HỎNG: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
