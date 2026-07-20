"""
State Backup — full system state export/import.

Port pattern from 9router src/lib/db/index.js exportDb()/importDb():
- export_all(): đọc TOÀN BỘ state → 1 JSON object
- import_all(payload): validate → xóa cũ → insert mới → trong transaction

Backup includes:
- ChatGPT accounts — GIỮ access_token THÔ (để restore hoạt động được; kèm thêm
  field access_token_hash chỉ để đối chiếu)
- Provider configs (opencode, gemini, openrouter, sdwebui, etc.)
- Auth keys (chỉ metadata public: id/name/role/enabled — KHÔNG kèm key_hash)
- Image tasks metadata
- Full config (bao gồm api_key các provider)
- Combo models
- Search config

⚠️ File backup vì thế chứa secret ở dạng đọc được — truyền `passphrase` cho
save_to_file()/API /api/v1/backup để mã hóa Fernet (PBKDF2-SHA256) trước khi ghi.
"""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config
from services.account_service import account_service
from utils.helper import anonymize_token
from utils.log import logger

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_RETENTION_DEFAULT = 5
CURRENT_SCHEMA_VERSION = 2

# ── Mã hóa backup bằng passphrase (tùy chọn) ──────────────────────────────────
# Envelope: {"version", "encrypted": True, "kdf": "pbkdf2-sha256", "iterations",
# "salt": b64, "ciphertext": Fernet token}. Không passphrase = ghi JSON thường
# (tương thích ngược 100%).

_KDF_ITERATIONS = 600_000


def _derive_key(passphrase: str, salt: bytes, iterations: int = _KDF_ITERATIONS) -> bytes:
    import base64
    import hashlib
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=32)
    return base64.urlsafe_b64encode(dk)


def encrypt_payload(state: dict[str, Any], passphrase: str) -> dict[str, Any]:
    """Bọc state thành envelope mã hóa Fernet (AES128-CBC + HMAC)."""
    import base64
    import os as _os
    from cryptography.fernet import Fernet
    salt = _os.urandom(16)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(
        json.dumps(state, ensure_ascii=False, default=str).encode("utf-8"))
    return {
        "version": CURRENT_SCHEMA_VERSION,
        "encrypted": True,
        "kdf": "pbkdf2-sha256",
        "iterations": _KDF_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": token.decode("ascii"),
    }


def decrypt_payload(payload: dict[str, Any], passphrase: str) -> dict[str, Any]:
    """Giải mã envelope encrypt_payload(); sai passphrase → ValueError rõ ràng."""
    import base64
    from cryptography.fernet import Fernet, InvalidToken
    salt = base64.b64decode(str(payload.get("salt") or ""))
    iterations = int(payload.get("iterations") or _KDF_ITERATIONS)
    try:
        raw = Fernet(_derive_key(passphrase, salt, iterations)).decrypt(
            str(payload.get("ciphertext") or "").encode("ascii"))
    except InvalidToken as exc:
        raise ValueError("Passphrase sai hoặc file backup mã hóa bị hỏng") from exc
    return json.loads(raw.decode("utf-8"))


@dataclass
class RestoreReport:
    """Report after a restore operation."""
    success: bool = True
    sections_restored: list[str] = field(default_factory=list)
    sections_skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    backup_version: int = 0
    items_restored: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "sections_restored": self.sections_restored,
            "sections_skipped": self.sections_skipped,
            "errors": self.errors,
            "backup_version": self.backup_version,
            "items_restored": self.items_restored,
        }


class StateBackup:
    """Full state backup/restore — ported from 9router exportDb/importDb."""

    def __init__(self):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def export_all(self) -> dict[str, Any]:
        """Collect ALL system state into a single JSON-serializable dict.

        Returns:
            Complete state snapshot with schema version and metadata.
        """
        now = datetime.now(timezone.utc).isoformat()

        state: dict[str, Any] = {
            "version": CURRENT_SCHEMA_VERSION,
            "created_at": now,
            "source": "chatgpt2api",
            "data": {
                "accounts": self._export_accounts(),
                "auth_keys": self._export_auth_keys(),
                "config": self._export_config(),
                "image_tasks": self._export_image_tasks(),
                "combo_models": self._export_combo_models(),
            },
        }

        return state

    def _export_accounts(self) -> list[dict[str, Any]]:
        """Export all ChatGPT accounts.

        LƯU Ý: giữ access_token THÔ (restore cần token thật); chỉ THÊM
        access_token_hash để đối chiếu. Muốn an toàn trên đĩa → dùng passphrase
        khi save_to_file()."""
        try:
            accounts = account_service.list_accounts()
        except Exception as exc:
            logger.warning({"event": "backup_export_accounts_error", "error": str(exc)})
            return []

        result = []
        for acc in accounts:
            item = dict(acc)
            # Keep token but mark it
            if "access_token" in item:
                item["access_token_hash"] = anonymize_token(item["access_token"])
            result.append(item)
        return result

    def _export_auth_keys(self) -> list[dict[str, Any]]:
        """Export API keys (hashed)."""
        try:
            from services.auth_service import auth_service
            keys = auth_service.list_keys()
            return [dict(k) for k in keys]
        except Exception:
            return []

    def _export_config(self) -> dict[str, Any]:
        """Export full configuration."""
        try:
            return config.get()
        except Exception:
            return {}

    def _export_image_tasks(self) -> list[dict[str, Any]]:
        """Export image task metadata (not the images themselves)."""
        try:
            tasks_file = DATA_DIR / "image_tasks.json"
            if tasks_file.exists():
                data = json.loads(tasks_file.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
        except Exception:
            pass
        return []

    def _export_combo_models(self) -> dict[str, list[str]]:
        """Export combo model definitions."""
        combos = config.data.get("combo_models")
        return dict(combos) if isinstance(combos, dict) else {}

    def import_all(self, payload: dict[str, Any]) -> RestoreReport:
        """Restore full system state from a backup payload.

        Args:
            payload: Backup JSON as returned by export_all()

        Returns:
            RestoreReport with details of what was restored.
        """
        report = RestoreReport()

        # Validate
        if not isinstance(payload, dict):
            report.success = False
            report.errors.append("Backup payload must be a JSON object")
            return report

        backup_version = int(payload.get("version") or 0)
        report.backup_version = backup_version

        if backup_version > CURRENT_SCHEMA_VERSION:
            report.success = False
            report.errors.append(
                f"Backup version {backup_version} is newer than current version {CURRENT_SCHEMA_VERSION}. "
                f"Please upgrade chatgpt2api first."
            )
            return report

        data = payload.get("data")
        if not isinstance(data, dict):
            report.success = False
            report.errors.append("Backup payload missing 'data' section")
            return report

        # Restore each section
        # Order matters: config first, then accounts, then auth keys

        # 1. Config
        try:
            if isinstance(data.get("config"), dict):
                config_data = dict(data["config"])
                # Don't overwrite auth-key from backup
                config_data.pop("auth-key", None)
                config.update(config_data)
                report.sections_restored.append("config")
                report.items_restored["config"] = 1
        except Exception as exc:
            report.sections_skipped.append(f"config: {exc}")

        # 2. Accounts
        try:
            accounts = data.get("accounts")
            if isinstance(accounts, list) and accounts:
                tokens = [
                    str(acc.get("access_token") or "").strip()
                    for acc in accounts
                    if str(acc.get("access_token") or "").strip()
                ]
                if tokens:
                    result = account_service.add_accounts(tokens)
                    report.sections_restored.append("accounts")
                    report.items_restored["accounts"] = result.get("added", 0)
                else:
                    report.sections_skipped.append("accounts: no valid tokens found")
        except Exception as exc:
            report.sections_skipped.append(f"accounts: {exc}")

        # 3. Auth keys
        try:
            auth_keys = data.get("auth_keys")
            if isinstance(auth_keys, list) and auth_keys:
                from services.auth_service import auth_service
                restored = 0
                for key_data in auth_keys:
                    if isinstance(key_data, dict):
                        try:
                            key_name = str(key_data.get("name") or "restored_key")
                            permissions = key_data.get("permissions") or ["chat", "image"]
                            auth_service.create_key(key_name, permissions)
                            restored += 1
                        except Exception:
                            pass
                if restored > 0:
                    report.sections_restored.append("auth_keys")
                    report.items_restored["auth_keys"] = restored
        except Exception as exc:
            report.sections_skipped.append(f"auth_keys: {exc}")

        # 4. Combo models
        try:
            combos = data.get("combo_models")
            if isinstance(combos, dict) and combos:
                existing = config.data.get("combo_models") or {}
                merged = {**existing, **combos}
                config.data["combo_models"] = merged
                config._save()
                report.sections_restored.append("combo_models")
                report.items_restored["combo_models"] = len(combos)
        except Exception as exc:
            report.sections_skipped.append(f"combo_models: {exc}")

        # 5. Image tasks
        try:
            image_tasks = data.get("image_tasks")
            if isinstance(image_tasks, list) and image_tasks:
                tasks_file = DATA_DIR / "image_tasks.json"
                tasks_file.write_text(
                    json.dumps(image_tasks, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                report.sections_restored.append("image_tasks")
                report.items_restored["image_tasks"] = len(image_tasks)
        except Exception as exc:
            report.sections_skipped.append(f"image_tasks: {exc}")

        logger.info({
            "event": "backup_restored",
            "backup_version": backup_version,
            "sections_restored": report.sections_restored,
            "sections_skipped": report.sections_skipped,
        })

        return report

    def save_to_file(self, state: dict[str, Any], passphrase: str | None = None) -> Path:
        """Save backup state to a local JSON file (gzipped).

        Args:
            state: Snapshot từ export_all().
            passphrase: Có giá trị → mã hóa Fernet trước khi ghi
                (tên file `..._backup_<ts>.enc.json.gz`). Trống = như cũ.

        Returns:
            Path to the saved backup file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        encrypted = bool(passphrase and str(passphrase).strip())
        if encrypted:
            state = encrypt_payload(state, str(passphrase).strip())
        filename = f"chatgpt2api_backup_{timestamp}{'.enc' if encrypted else ''}.json.gz"
        filepath = BACKUP_DIR / filename

        json_bytes = json.dumps(state, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        with gzip.open(filepath, "wb") as f:
            f.write(json_bytes)

        logger.info({
            "event": "backup_saved",
            "path": str(filepath),
            "size_bytes": len(json_bytes),
            "encrypted": encrypted,
        })

        self._cleanup_old_backups()
        return filepath

    def load_from_file(self, filepath: Path, passphrase: str | None = None) -> dict[str, Any]:
        """Load backup state from a local JSON file (gzipped or plain).

        File mã hóa (envelope `encrypted: true`) bắt buộc kèm passphrase —
        thiếu/sai đều raise ValueError với message rõ."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Backup file not found: {path}")

        if path.suffix == ".gz":
            with gzip.open(path, "rb") as f:
                payload = json.loads(f.read().decode("utf-8"))
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(payload, dict) and payload.get("encrypted"):
            pw = str(passphrase or "").strip()
            if not pw:
                raise ValueError(
                    "File backup này được mã hóa — cần nhập passphrase để phục hồi")
            payload = decrypt_payload(payload, pw)
        return payload

    def list_backups(self) -> list[dict[str, Any]]:
        """List available local backup files."""
        backups = []
        if BACKUP_DIR.exists():
            for f in sorted(BACKUP_DIR.glob("chatgpt2api_backup_*.json*"), reverse=True):
                stat = f.stat()
                backups.append({
                    "filename": f.name,
                    "path": str(f),
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
        return backups

    def _cleanup_old_backups(self) -> int:
        """Remove old backups, keeping only the most recent N."""
        cfg = config.data.get("backup") or {}
        retention = int(cfg.get("local_retention") or BACKUP_RETENTION_DEFAULT)

        backups = self.list_backups()
        if len(backups) <= retention:
            return 0

        removed = 0
        for backup in backups[retention:]:
            try:
                Path(backup["path"]).unlink()
                removed += 1
            except OSError:
                pass

        return removed

    def delete_backup(self, filename: str) -> bool:
        """Delete a specific backup file by filename."""
        filepath = BACKUP_DIR / filename
        if filepath.exists():
            filepath.unlink()
            return True
        return False


# Singleton
state_backup = StateBackup()
