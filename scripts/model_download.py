"""Tải artifact model có SHA-256 và chỉ thay file đích sau khi xác minh."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path


class IntegrityError(RuntimeError):
    """Artifact tải về không khớp danh tính đã ghim."""


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
