"""Tải artifact model có SHA-256 và chỉ thay file đích sau khi xác minh."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path


class IntegrityError(RuntimeError):
    """Artifact tải về không khớp danh tính đã ghim."""


MODEL_MANIFEST = ".source.sha256"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual.lower() != str(expected).strip().lower():
        raise IntegrityError(
            f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}"
        )


def is_verified(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    try:
        verify_sha256(path, expected)
    except (IntegrityError, OSError):
        return False
    return True


def replace_verified(source: Path, destination: Path, expected: str) -> None:
    """Kiểm file tạm rồi rename nguyên tử trong cùng filesystem."""
    verify_sha256(source, expected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def download_verified(
    url: str,
    destination: Path,
    expected: str,
    *,
    timeout: float = 600,
) -> None:
    """Tải vào file tạm cạnh đích; sai hash thì giữ nguyên file cũ."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".download", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(raw_temp)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, temporary.open("wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        replace_verified(temporary, destination, expected)
    finally:
        temporary.unlink(missing_ok=True)


def install_verified_files(
    staging: Path,
    destination: Path,
    source_sha256: str,
    filenames: list[str],
) -> None:
    """Chỉ công bố bộ file đã đủ; marker chứa hash của từng file đã cài."""
    names = sorted({Path(name).name for name in filenames})
    if not names or any(not (staging / name).is_file() for name in names):
        raise IntegrityError("model archive is missing required extracted files")

    hashes = {name: sha256_file(staging / name) for name in names}
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / MODEL_MANIFEST
    # Marker cũ không được sống qua một lần cài dở dang.
    marker.unlink(missing_ok=True)
    for name in names:
        os.replace(staging / name, destination / name)

    payload = json.dumps(
        {"source_sha256": source_sha256, "files": hashes},
        ensure_ascii=True,
        sort_keys=True,
    ).encode("ascii") + b"\n"
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{MODEL_MANIFEST}.", suffix=".tmp", dir=destination
    )
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(raw_temp, marker)
    finally:
        Path(raw_temp).unlink(missing_ok=True)


def installation_verified(
    destination: Path,
    source_sha256: str,
    required: list[str] | None = None,
) -> bool:
    """Kiểm nguồn archive lẫn hash từng artifact sau khi giải nén."""
    try:
        manifest = json.loads((destination / MODEL_MANIFEST).read_text("ascii"))
        if manifest.get("source_sha256") != source_sha256:
            return False
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            return False
        if required and not set(required).issubset(files):
            return False
        return all(
            Path(name).name == name
            and isinstance(expected, str)
            and is_verified(destination / name, expected)
            for name, expected in files.items()
        )
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return False
