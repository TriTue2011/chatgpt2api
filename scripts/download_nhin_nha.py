#!/usr/bin/env python3
"""Tải model «mắt của nhà» về data/nhin-nha/ — KHÔNG nằm trong image.

Hai loại model, cùng nguyên tắc Kokoro/Piper (code trong image, model ngoài volume):

* YOLO26 (Ultralytics, AGPL-3.0) — nhận loại vật thể + toạ độ. Một tệp ONNX.
* InsightFace buffalo_s / buffalo_l (chỉ phi thương mại) — dò mặt + vector mặt.
  Gói zip có 5 model; chỉ giữ HAI tệp cần (dò + vector), bỏ 3 tệp còn lại
  (riêng 1k3d68.onnx đã 144 MB) vì đĩa máy chủ chật.

    python scripts/download_nhin_nha.py                        # yolo26n + buffalo_s
    python scripts/download_nhin_nha.py --yolo yolo26s         # thêm YOLO khác
    python scripts/download_nhin_nha.py --mat buffalo_l        # thêm bộ mặt khác
    python scripts/download_nhin_nha.py --list                 # xem danh mục
    python scripts/download_nhin_nha.py --check                # chỉ kiểm tra

Chạy trong container:
    docker exec c2a /app/.venv/bin/python scripts/download_nhin_nha.py

Mọi tệp đều so SHA-256 đã ghim trong services/yolo_nha.py và
services/khuon_mat_nha.py — lệch là bỏ, không dùng.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get("NHIN_NHA_DIR") or ROOT / "data" / "nhin-nha")


def _nap(ten: str):
    # Nạp THẲNG file danh mục, không qua `from services import ...` (import cả
    # gói kéo theo services.config và đòi CHATGPT2API_AUTH_KEY) — cùng nếp
    # download_kokoro_vi.py.
    spec = importlib.util.spec_from_file_location(ten, ROOT / "services" / f"{ten}.py")
    m = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    sys.modules[ten] = m
    spec.loader.exec_module(m)                          # type: ignore[union-attr]
    return m


yn = _nap("yolo_nha")
km = _nap("khuon_mat_nha")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while khoi := f.read(1 << 20):
            h.update(khoi)
    return h.hexdigest()


def _tai(url: str, dich: Path) -> None:
    """Tải về tệp tạm cạnh đích — đứt giữa chừng không để lại tệp dở dang."""
    print(f"  tải {url}")
    with urllib.request.urlopen(url, timeout=60) as r, dich.open("wb") as f:  # noqa: S310 — URL hằng
        tong = int(r.headers.get("Content-Length") or 0)
        da = 0
        while khoi := r.read(1 << 20):
            f.write(khoi)
            da += len(khoi)
            if tong:
                print(f"\r  {da / 1e6:6.1f}/{tong / 1e6:.1f} MB", end="", flush=True)
    print()


def _tai_yolo(m) -> bool:
    dich = DEST / m.tep
    if dich.is_file() and _sha(dich) == m.sha256:
        print(f"[da co] {m.tep}")
        return True
    with tempfile.NamedTemporaryFile(dir=DEST, suffix=".part", delete=False) as t:
        tam = Path(t.name)
    try:
        _tai(yn.PHAT_HANH + m.tep, tam)
        if _sha(tam) != m.sha256:
            print(f"[HONG] {m.tep}: SHA-256 không khớp bản đã ghim — bỏ", file=sys.stderr)
            return False
        os.replace(tam, dich)
        # NamedTemporaryFile tạo quyền 0600 — tiến trình dịch vụ khác chủ tệp
        # thì không đọc nổi model vừa tải.
        dich.chmod(0o644)
        print(f"[ok] {m.tep} ({dich.stat().st_size / 1e6:.1f} MB)")
        return True
    finally:
        tam.unlink(missing_ok=True)


def _tai_mat(b) -> bool:
    thu_muc = DEST / b.ma
    can = {b.tep_do: b.sha_do, b.tep_vector: b.sha_vector}
    if all((thu_muc / t).is_file() and _sha(thu_muc / t) == s for t, s in can.items()):
        print(f"[da co] {b.ma}")
        return True
    thu_muc.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DEST) as tam:
        goi = Path(tam) / b.zip
        _tai(km.PHAT_HANH + b.zip, goi)
        with zipfile.ZipFile(goi) as z:
            for ten, sha in can.items():
                # Lấy đúng tên tệp theo phần CUỐI đường dẫn trong zip, không
                # giải nén cả gói — không có tên nào đi ra ngoài thư mục đích.
                muc = next((i for i in z.infolist() if Path(i.filename).name == ten), None)
                if muc is None:
                    print(f"[HONG] {b.zip} thiếu {ten}", file=sys.stderr)
                    return False
                ra = Path(tam) / ten
                with z.open(muc) as src, ra.open("wb") as dst:
                    while khoi := src.read(1 << 20):
                        dst.write(khoi)
                if _sha(ra) != sha:
                    print(f"[HONG] {ten}: SHA-256 không khớp bản đã ghim — bỏ", file=sys.stderr)
                    return False
                os.replace(ra, thu_muc / ten)
                print(f"[ok] {b.ma}/{ten} ({(thu_muc / ten).stat().st_size / 1e6:.1f} MB)")
    return True


def _kiem(ds_yolo, ds_mat) -> bool:
    du = True
    for m in ds_yolo:
        co = (DEST / m.tep).is_file()
        du = du and co
        print(f"[{'co' if co else 'THIEU'}] {m.tep}")
    for b in ds_mat:
        co = all((DEST / b.ma / t).is_file() for t in (b.tep_do, b.tep_vector))
        du = du and co
        print(f"[{'co' if co else 'THIEU'}] {b.ma}")
    return du


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yolo", action="append", help=f"mã YOLO (mặc định {yn.MAC_DINH})")
    ap.add_argument("--mat", action="append", help=f"bộ mặt (mặc định {km.MAC_DINH})")
    ap.add_argument("--list", action="store_true", help="liệt kê danh mục")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra, không tải")
    args = ap.parse_args()

    if args.list:
        for m in yn.MODELS:
            print(f"{'✓' if (DEST / m.tep).is_file() else ' '} --yolo {m.ma:10} {m.mb:6.1f} MB  {m.mo_ta}")
        for b in km.BO:
            co = all((DEST / b.ma / t).is_file() for t in (b.tep_do, b.tep_vector))
            print(f"{'✓' if co else ' '} --mat  {b.ma:10} {b.zip_mb:6.1f} MB  {b.mo_ta}")
        return 0

    # Chỉ nêu một loại thì chỉ tải loại đó; không nêu gì thì tải bộ mặc định.
    ma_yolo = args.yolo or ([] if args.mat else [yn.MAC_DINH])
    ma_mat = args.mat or ([] if args.yolo else [km.MAC_DINH])
    ds_yolo = [yn.get(x) for x in ma_yolo]
    ds_mat = [km.get(x) for x in ma_mat]
    la = [x for x, m in zip(ma_yolo + ma_mat, ds_yolo + ds_mat) if m is None]
    if la:
        print(f"Không có trong danh mục: {', '.join(la)} (xem --list)", file=sys.stderr)
        return 2
    print(f"Thư mục: {DEST}")
    if args.check:
        return 0 if _kiem(ds_yolo, ds_mat) else 1

    DEST.mkdir(parents=True, exist_ok=True)
    ok = all([_tai_yolo(m) for m in ds_yolo] + [_tai_mat(b) for b in ds_mat])
    print("\nXong. Model nạp ở lần dùng đầu tiên, không cần khởi động lại." if ok
          else "\nCó tệp tải hỏng — chạy lại lệnh.")
    return 0 if ok and _kiem(ds_yolo, ds_mat) else 1


if __name__ == "__main__":
    sys.exit(main())
